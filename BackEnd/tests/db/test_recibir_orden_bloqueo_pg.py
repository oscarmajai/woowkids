"""Contra PostgreSQL real: `recibir` bloquea los insumos por id. Si los
bloqueara en el orden de las líneas (por nombre), con nombres repetidos dos
recepciones podrían bloquear los mismos insumos en orden distinto y trabarse."""

import asyncio
import uuid

import asyncpg
from app.services import compra_service

from tests.db.conftest import Escenario
from tests.db.inventario_datos import crear_compra, crear_insumo, linea, unidad


async def test_recepciones_simultaneas_con_insumos_homonimos_no_se_traban(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    """Dos insumos con el mismo nombre en compras con las líneas en orden
    inverso: antes el orden de bloqueo dependía del nombre (empate) y podía
    cruzarse. Ahora todas las recepciones bloquean en orden de id."""
    async with pool.acquire() as conn:
        pza = await unidad(conn, "pza")
        nombre = f"Pan {uuid.uuid4().hex[:6]}"
        a = await crear_insumo(conn, escenario, nombre=nombre)
        b = await crear_insumo(conn, escenario, nombre=nombre)
        compras = []
        for i in range(8):
            orden = (a, b) if i % 2 else (b, a)
            compras.append(
                await crear_compra(conn, escenario, [linea(x, pza, "1", "1") for x in orden])
            )

    async def _recibir(compra_id: uuid.UUID) -> None:
        async with pool.acquire() as c:
            await compra_service.recibir(c, compra_id, escenario.usuario_id)

    await asyncio.gather(*(_recibir(c) for c in compras))

    async with pool.acquire() as conn:
        stocks = await conn.fetch(
            "SELECT stock_actual FROM public.insumos WHERE id = ANY($1::uuid[])", [a, b]
        )
        assert [s["stock_actual"] for s in stocks] == [8, 8]
