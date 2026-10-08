"""El stock inicial de un insumo entra con movimiento en el kardex y capa de
costo PEPS, contra PostgreSQL real. Sin ninguno de los dos, el kardex no
cuadraría con stock_actual y esas unidades quedarían sin costo."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import asyncpg
from app.schemas.auth import TokenData
from app.schemas.compra import CompraCrear, DetalleCompraItem
from app.schemas.insumo import InsumoCrear, InsumoUpdate
from app.services import compra_service, insumo_service

from tests.db.conftest import Escenario


def _token(esc: Escenario) -> TokenData:
    return TokenData(
        sub=str(esc.usuario_id),
        email="cajero@test.local",
        role="3",
        branch_id=esc.sucursal_id,
        jti=uuid.uuid4().hex,
        exp=datetime.now(UTC) + timedelta(hours=1),
    )


async def _crear_insumo(
    conn: asyncpg.Connection, esc: Escenario, stock: str, costo: str | None
) -> uuid.UUID:
    pza = await conn.fetchval("SELECT id FROM public.unidades_medida WHERE codigo = 'pza'")
    insumo = await insumo_service.crear(
        conn,
        InsumoCrear(
            sucursal_id=esc.sucursal_id,
            nombre=f"Servilletas {uuid.uuid4().hex[:8]}",
            unidad_base_id=pza,
            unidad_compra_id=pza,
            stock_inicial=Decimal(stock),
            costo_unitario=Decimal(costo) if costo is not None else None,
        ),
        _token(esc),
    )
    return insumo.id


async def _kardex(conn: asyncpg.Connection, insumo_id: uuid.UUID) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT
            (SELECT stock_actual FROM public.insumos WHERE id = $1) AS stock,
            (SELECT COALESCE(SUM(CASE WHEN tipo IN ('E', 'A') THEN cantidad ELSE -cantidad END), 0)
               FROM public.movimientos_inventario WHERE insumo_id = $1) AS saldo_kardex,
            (SELECT COALESCE(SUM(cantidad_restante), 0)
               FROM public.capas_costo_insumo WHERE insumo_id = $1) AS capas,
            (SELECT COALESCE(SUM(cantidad_restante * costo_unitario), 0)
               FROM public.capas_costo_insumo WHERE insumo_id = $1) AS valor_capas
        """,
        insumo_id,
    )
    return dict(row)


async def test_stock_inicial_crea_movimiento_y_capa_y_el_kardex_cuadra(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        insumo_id = await _crear_insumo(conn, escenario, "50", "0.50")

        movimientos = await conn.fetch(
            "SELECT tipo, motivo::text AS motivo, cantidad, stock_resultante, costo_total, "
            "creado_por FROM public.movimientos_inventario WHERE insumo_id = $1",
            insumo_id,
        )
        capas = await conn.fetch(
            "SELECT cantidad_inicial, cantidad_restante, costo_unitario, origen "
            "FROM public.capas_costo_insumo WHERE insumo_id = $1",
            insumo_id,
        )
        kardex = await _kardex(conn, insumo_id)

    assert [dict(m) for m in movimientos] == [
        {
            "tipo": "E",
            "motivo": "inventario_inicial",
            "cantidad": Decimal("50"),
            "stock_resultante": Decimal("50"),
            "costo_total": Decimal("25"),
            "creado_por": escenario.usuario_id,
        }
    ]
    assert [dict(c) for c in capas] == [
        {
            "cantidad_inicial": Decimal("50"),
            "cantidad_restante": Decimal("50"),
            "costo_unitario": Decimal("0.5"),
            "origen": "inicial",
        }
    ]
    assert kardex == {
        "stock": Decimal("50"),
        "saldo_kardex": Decimal("50"),
        "capas": Decimal("50"),
        "valor_capas": Decimal("25"),
    }


async def test_stock_inicial_y_compra_posterior_siguen_cuadrando(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    # 50 iniciales + compra de 100 → kardex 150, capas 150.
    async with pool.acquire() as conn:
        insumo_id = await _crear_insumo(conn, escenario, "50", "0.50")
        pza = await conn.fetchval("SELECT id FROM public.unidades_medida WHERE codigo = 'pza'")
        proveedor_id = await conn.fetchval(
            "INSERT INTO public.proveedores (sucursal_id, nombre) VALUES ($1, $2) RETURNING id",
            escenario.sucursal_id,
            f"Proveedor {uuid.uuid4().hex[:8]}",
        )
        compra = await compra_service.crear(
            conn,
            CompraCrear(
                sucursal_id=escenario.sucursal_id,
                proveedor_id=proveedor_id,
                detalles=[
                    DetalleCompraItem(
                        insumo_id=insumo_id,
                        unidad_medida_id=pza,
                        cantidad=Decimal("100"),
                        costo_unitario=Decimal("0.30"),
                    )
                ],
            ),
            escenario.usuario_id,
        )
        await compra_service.recibir(conn, compra.id, escenario.usuario_id)
        kardex = await _kardex(conn, insumo_id)

    assert kardex == {
        "stock": Decimal("150"),
        "saldo_kardex": Decimal("150"),
        "capas": Decimal("150"),
        "valor_capas": Decimal("55"),
    }


async def test_insumo_sin_stock_inicial_no_genera_movimiento_ni_capa(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        insumo_id = await _crear_insumo(conn, escenario, "0", "0.50")
        kardex = await _kardex(conn, insumo_id)
        movimientos = await conn.fetchval(
            "SELECT COUNT(*) FROM public.movimientos_inventario WHERE insumo_id = $1", insumo_id
        )
    assert movimientos == 0
    assert kardex["stock"] == kardex["capas"] == 0


async def test_stock_inicial_sin_costo_crea_capa_a_cero(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        insumo_id = await _crear_insumo(conn, escenario, "10", None)
        kardex = await _kardex(conn, insumo_id)
    assert (kardex["stock"], kardex["saldo_kardex"], kardex["capas"]) == (10, 10, 10)
    assert kardex["valor_capas"] == 0


async def test_editar_insumo_no_cambia_el_stock(pool: asyncpg.Pool, escenario: Escenario) -> None:
    # La edición no expone stock_actual: el stock solo se mueve con movimientos.
    async with pool.acquire() as conn:
        insumo_id = await _crear_insumo(conn, escenario, "50", "0.50")
        body = InsumoUpdate.model_validate({"stock_actual": "999", "stock_minimo": "5"})
        out = await insumo_service.actualizar(conn, insumo_id, body, _token(escenario))
        kardex = await _kardex(conn, insumo_id)
    assert out.stock_actual == 50
    assert out.stock_minimo == 5
    assert kardex["stock"] == kardex["saldo_kardex"] == kardex["capas"] == 50
