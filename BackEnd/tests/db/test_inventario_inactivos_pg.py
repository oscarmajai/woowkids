"""Contra PostgreSQL real: compras, movimientos y presentaciones sobre insumos
o proveedores eliminados (borrado lógico) responden 409."""

from decimal import Decimal

import asyncpg
import pytest
from app.exceptions.inventario import RecursoInactivoError
from app.schemas.movimiento_inventario import ConteoFisicoCreate, MovimientoManualCreate
from app.schemas.presentacion_insumo import PresentacionCrear
from app.services import insumo_service, inventario_service, presentacion_insumo_service

from tests.db.conftest import Escenario
from tests.db.inventario_datos import (
    crear_compra,
    crear_insumo,
    crear_proveedor,
    linea,
    token,
    unidad,
)


async def test_compra_con_proveedor_eliminado_responde_409(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        pza = await unidad(conn, "pza")
        insumo_id = await crear_insumo(conn, escenario)
        proveedor_id = await crear_proveedor(conn, escenario)
        await conn.execute(
            "UPDATE public.proveedores SET activo = FALSE WHERE id = $1", proveedor_id
        )
        with pytest.raises(RecursoInactivoError) as exc:
            await crear_compra(conn, escenario, [linea(insumo_id, pza, "1", "1")], proveedor_id)
        assert exc.value.status_code == 409
        assert (
            await conn.fetchval(
                "SELECT COUNT(*) FROM public.compras WHERE proveedor_id = $1", proveedor_id
            )
            == 0
        )


async def test_compra_con_insumo_eliminado_responde_409(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        pza = await unidad(conn, "pza")
        insumo_id = await crear_insumo(conn, escenario)
        await insumo_service.eliminar(conn, insumo_id)
        with pytest.raises(RecursoInactivoError) as exc:
            await crear_compra(conn, escenario, [linea(insumo_id, pza, "1", "1")])
        assert exc.value.status_code == 409


async def test_movimientos_y_presentaciones_sobre_insumo_eliminado_responden_409(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        insumo_id = await crear_insumo(conn, escenario, stock="10", costo="1")
        await insumo_service.eliminar(conn, insumo_id)

        with pytest.raises(RecursoInactivoError):
            await inventario_service.registrar_ajuste_manual(
                conn,
                insumo_id,
                MovimientoManualCreate(tipo="E", cantidad=Decimal("5")),
                escenario.usuario_id,
            )
        with pytest.raises(RecursoInactivoError):
            await inventario_service.registrar_conteo_fisico(
                conn,
                insumo_id,
                ConteoFisicoCreate(stock_contado=Decimal("3")),
                escenario.usuario_id,
            )
        with pytest.raises(RecursoInactivoError):
            await presentacion_insumo_service.crear(
                conn,
                insumo_id,
                PresentacionCrear(nombre="Caja", equivalencia_base=Decimal("10")),
                token(escenario),
            )

        assert await conn.fetchval(
            "SELECT stock_actual FROM public.insumos WHERE id = $1", insumo_id
        ) == Decimal("10")
        assert (
            await conn.fetchval(
                "SELECT COUNT(*) FROM public.presentaciones_insumo WHERE insumo_id = $1", insumo_id
            )
            == 0
        )
