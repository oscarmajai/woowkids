"""Orden del kardex, de las capas PEPS y de las líneas de compra, contra
PostgreSQL real.

Los movimientos de una misma transacción comparten `creado`; para que el kardex
no los ordene de forma arbitraria ni las capas PEPS de una misma recepción se
consuman en el orden de un uuid, ambos siguen la secuencia de inserción
(migración 098). Las líneas de una compra se listan en el orden en que se
capturaron, no por nombre del insumo (migración 099)."""

import uuid
from decimal import Decimal

import asyncpg
from app.repositories import compra_repository, movimiento_inventario_repository
from app.services import compra_service, costeo_service

from tests.db.conftest import Escenario
from tests.db.inventario_datos import crear_compra, crear_insumo, linea, unidad


async def test_kardex_sigue_el_orden_de_insercion_en_una_misma_transaccion(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        pza = await unidad(conn, "pza")
        insumo_id = await crear_insumo(conn, escenario)
        # Cinco líneas del mismo insumo: sus movimientos comparten `creado`.
        lineas = [linea(insumo_id, pza, str(n), "1") for n in (1, 2, 3, 4, 5)]
        compra_id = await crear_compra(conn, escenario, lineas)
        await compra_service.recibir(conn, compra_id, escenario.usuario_id)

        kardex = await movimiento_inventario_repository.listar_por_insumo(conn, insumo_id)
        assert len({m["creado"] for m in kardex}) == 1
        # Del más reciente al más viejo: el saldo baja de línea en línea.
        assert [m["stock_resultante"] for m in kardex] == [15, 10, 6, 3, 1]
        assert [m["cantidad"] for m in kardex] == [5, 4, 3, 2, 1]


async def test_peps_consume_las_capas_de_una_recepcion_en_orden_de_captura(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        pza = await unidad(conn, "pza")
        insumo_id = await crear_insumo(conn, escenario)
        lineas = [linea(insumo_id, pza, "1", costo) for costo in ("1", "2", "3", "4", "5", "6")]
        compra_id = await crear_compra(conn, escenario, lineas)
        await compra_service.recibir(conn, compra_id, escenario.usuario_id)

        async with conn.transaction():
            costos = [
                await costeo_service.consumir(conn, insumo_id, Decimal("1")) for _ in range(6)
            ]
        assert costos == [Decimal(c) for c in ("1", "2", "3", "4", "5", "6")]


async def test_lineas_de_la_compra_se_listan_en_orden_de_captura(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    async with pool.acquire() as conn:
        pza = await unidad(conn, "pza")
        nombres = ["Zanahoria", "Aceite", "Mostaza"]
        sufijo = uuid.uuid4().hex[:6]
        ids = [await crear_insumo(conn, escenario, nombre=f"{n} {sufijo}") for n in nombres]
        compra_id = await crear_compra(conn, escenario, [linea(i, pza, "1", "1") for i in ids])

        detalles = await compra_repository.listar_detalles(conn, compra_id)
        assert [d["insumo_id"] for d in detalles] == ids
