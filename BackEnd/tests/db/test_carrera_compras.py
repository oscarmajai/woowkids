"""C5: recibir (y cancelar/editar) la misma compra en paralelo, cada petición
con su propia conexión del pool. Antes del arreglo, 4 recepciones simultáneas
de una compra de 10 respondían todas 200 y el stock subía 40."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any

import asyncpg
from app.exceptions import Conflicto
from app.schemas.compra import (
    CompraEditar,
    DetalleCompraItem,
    LineaRecepcion,
    RecibirCompraRequest,
)
from app.services import compra_service

from tests.db.conftest import N_CONCURRENTES, Escenario


async def _en_paralelo(
    pool: asyncpg.Pool, n: int, fn: Callable[[asyncpg.Connection, int], Awaitable[Any]]
) -> list[Any]:
    async def una(i: int) -> Any:
        async with pool.acquire() as conn:
            return await fn(conn, i)

    return await asyncio.gather(*(una(i) for i in range(n)), return_exceptions=True)


async def _unidad_pza(conn: asyncpg.Connection) -> uuid.UUID:
    return await conn.fetchval("SELECT id FROM public.unidades_medida WHERE codigo = 'pza'")


async def _crear_compra(
    pool: asyncpg.Pool, esc: Escenario, cantidad: Decimal
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Proveedor + insumo (stock 0, unidad pza) + compra pendiente de una línea.
    Devuelve (compra_id, detalle_id, insumo_id)."""
    sufijo = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        pza = await _unidad_pza(conn)
        proveedor_id = await conn.fetchval(
            "INSERT INTO public.proveedores (sucursal_id, nombre) VALUES ($1, $2) RETURNING id",
            esc.sucursal_id,
            f"Proveedor {sufijo}",
        )
        insumo_id = await conn.fetchval(
            """
            INSERT INTO public.insumos (sucursal_id, nombre, unidad_base_id, unidad_compra_id)
            VALUES ($1, $2, $3, $3) RETURNING id
            """,
            esc.sucursal_id,
            f"Servilletas {sufijo}",
            pza,
        )
        compra_id = await conn.fetchval(
            "INSERT INTO public.compras (sucursal_id, proveedor_id, total) "
            "VALUES ($1, $2, $3) RETURNING id",
            esc.sucursal_id,
            proveedor_id,
            cantidad * Decimal("0.5"),
        )
        detalle_id = await conn.fetchval(
            """
            INSERT INTO public.detalle_compras
                (compra_id, insumo_id, unidad_medida_id, cantidad, costo_unitario)
            VALUES ($1, $2, $3, $4, 0.5) RETURNING id
            """,
            compra_id,
            insumo_id,
            pza,
            cantidad,
        )
    return compra_id, detalle_id, insumo_id


async def _estado(pool: asyncpg.Pool, compra_id: uuid.UUID, insumo_id: uuid.UUID) -> dict[str, Any]:
    async with pool.acquire() as conn:
        return dict(
            await conn.fetchrow(
                """
                SELECT
                    (SELECT estado FROM public.compras WHERE id = $1) AS estado,
                    (SELECT stock_actual FROM public.insumos WHERE id = $2) AS stock,
                    (SELECT COALESCE(SUM(cantidad_recibida), 0)
                       FROM public.detalle_compras WHERE compra_id = $1) AS recibido,
                    (SELECT COUNT(*) FROM public.movimientos_inventario
                      WHERE referencia_id = $1) AS movimientos,
                    (SELECT COUNT(*) FROM public.capas_costo_insumo
                      WHERE referencia_id = $1) AS capas
                """,
                compra_id,
                insumo_id,
            )
        )


async def test_recibir_misma_compra_en_paralelo_suma_stock_una_sola_vez(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    compra_id, _, insumo_id = await _crear_compra(pool, escenario, Decimal("10"))

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, _i: compra_service.recibir(c, compra_id, escenario.usuario_id),
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert len(exitos) == 1
    assert len(errores) == N_CONCURRENTES - 1
    assert all(isinstance(e, Conflicto) and e.status_code == 409 for e in errores), errores
    assert all(e.detail["message"] == "La compra ya fue recibida." for e in errores)

    estado = await _estado(pool, compra_id, insumo_id)
    assert estado == {"estado": "R", "stock": 10, "recibido": 10, "movimientos": 1, "capas": 1}


async def test_recepciones_parciales_en_paralelo_no_exceden_lo_pedido(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    # Cada petición pide 2 de 10: solo caben 5; el resto llega con la compra ya
    # completa y recibe 409. (Con 3 de 10 la cuarta pediría más de lo pendiente
    # y, desde M23, recibe 422 en vez de recortarse: ver test_recepcion_compras.)
    compra_id, detalle_id, insumo_id = await _crear_compra(pool, escenario, Decimal("10"))
    body = RecibirCompraRequest(lineas=[LineaRecepcion(detalle_id=detalle_id, cantidad=2)])

    resultados = await _en_paralelo(
        pool,
        N_CONCURRENTES,
        lambda c, _i: compra_service.recibir(c, compra_id, escenario.usuario_id, body),
    )

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert len(exitos) == 5
    assert all(isinstance(e, Conflicto) for e in errores), errores

    estado = await _estado(pool, compra_id, insumo_id)
    assert estado == {"estado": "R", "stock": 10, "recibido": 10, "movimientos": 5, "capas": 5}


async def test_recibir_y_cancelar_en_paralelo_solo_gana_uno(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    compra_id, _, insumo_id = await _crear_compra(pool, escenario, Decimal("10"))

    async def op(c: asyncpg.Connection, i: int) -> Any:
        if i % 2 == 0:
            return await compra_service.recibir(c, compra_id, escenario.usuario_id)
        return await compra_service.cancelar(c, compra_id)

    resultados = await _en_paralelo(pool, N_CONCURRENTES, op)

    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    errores = [r for r in resultados if isinstance(r, BaseException)]
    assert len(exitos) == 1
    assert all(isinstance(e, Conflicto) for e in errores), errores

    estado = await _estado(pool, compra_id, insumo_id)
    if estado["estado"] == "R":
        assert (estado["stock"], estado["recibido"], estado["movimientos"]) == (10, 10, 1)
    else:
        assert estado["estado"] == "C"
        assert (estado["stock"], estado["recibido"], estado["movimientos"]) == (0, 0, 0)


async def test_editar_y_recibir_en_paralelo_no_pierde_lo_recibido(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    compra_id, _, insumo_id = await _crear_compra(pool, escenario, Decimal("10"))
    async with pool.acquire() as conn:
        pza = await _unidad_pza(conn)
        proveedor_id = await conn.fetchval(
            "SELECT proveedor_id FROM public.compras WHERE id = $1", compra_id
        )
    edicion = CompraEditar(
        proveedor_id=proveedor_id,
        detalles=[
            DetalleCompraItem(
                insumo_id=insumo_id,
                unidad_medida_id=pza,
                cantidad=Decimal("20"),
                costo_unitario=Decimal("0.5"),
            )
        ],
    )

    async def op(c: asyncpg.Connection, i: int) -> Any:
        if i % 2 == 0:
            return await compra_service.recibir(c, compra_id, escenario.usuario_id)
        return await compra_service.editar(c, compra_id, edicion)

    resultados = await _en_paralelo(pool, N_CONCURRENTES, op)

    assert all(isinstance(r, Conflicto) for r in resultados if isinstance(r, BaseException))
    # Lo que entró al stock es exactamente lo que dicen las líneas de la compra:
    # una edición nunca borra una línea ya recibida.
    estado = await _estado(pool, compra_id, insumo_id)
    assert estado["estado"] == "R"
    assert estado["stock"] == estado["recibido"]
    assert estado["movimientos"] == 1
