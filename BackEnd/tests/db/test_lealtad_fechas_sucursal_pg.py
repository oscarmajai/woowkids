"""Los filtros desde/hasta del reporte y del kardex de lealtad son días de la
sucursal, no de UTC. Antes, comparar ``creado`` con una fecha sola la tomaba
como medianoche UTC (las 18:00 de México): lo de la tarde-noche caía en el día
siguiente.

Requiere ``TEST_DATABASE_URL`` (BD desechable con ``sql/schema_maestro.sql``).
Cada test corre en una transacción que se revierte al final.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta

import asyncpg
import pytest
import pytest_asyncio
from app.repositories import lealtad_repository

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL no definida (BD desechable)"
)

CELULAR = "3300000077"
DIA = date(2026, 10, 3)


@pytest_asyncio.fixture
async def conn() -> AsyncIterator[asyncpg.Connection]:
    assert TEST_DATABASE_URL
    c = await asyncpg.connect(TEST_DATABASE_URL)
    tx = c.transaction()
    await tx.start()
    try:
        yield c
    finally:
        await tx.rollback()
        await c.close()


async def _sucursal_con_venta_a_las_20(conn: asyncpg.Connection) -> uuid.UUID:
    """Sucursal en Ciudad de México con 10 puntos otorgados el 3 de octubre a
    las 20:00 locales (= 4 de octubre 02:00 UTC)."""
    sucursal_id = await conn.fetchval(
        "INSERT INTO public.sucursales (nombre, zona_horaria) "
        "VALUES ($1, 'America/Mexico_City') RETURNING id",
        f"Lealtad fechas {uuid.uuid4().hex[:8]}",
    )
    await conn.execute(
        """
        INSERT INTO public.movimientos_puntos
            (sucursal_id, celular, tipo, puntos, saldo_resultante, creado)
        VALUES ($1, $2, 'O', 10, 10,
                ($3::date + time '20:00') AT TIME ZONE 'America/Mexico_City')
        """,
        sucursal_id,
        CELULAR,
        DIA,
    )
    return sucursal_id


async def test_la_venta_de_la_noche_cuenta_en_su_dia(conn: asyncpg.Connection) -> None:
    sucursal_id = await _sucursal_con_venta_a_las_20(conn)

    del_dia = await lealtad_repository.reporte_agregado(conn, sucursal_id, DIA, DIA)
    assert del_dia["total_otorgado"] == 10
    siguiente = DIA + timedelta(days=1)
    del_siguiente = await lealtad_repository.reporte_agregado(
        conn, sucursal_id, siguiente, siguiente
    )
    assert del_siguiente["total_otorgado"] == 0


async def test_top_clientes_y_kardex_usan_el_dia_de_la_sucursal(
    conn: asyncpg.Connection,
) -> None:
    sucursal_id = await _sucursal_con_venta_a_las_20(conn)

    top = await lealtad_repository.top_clientes(conn, sucursal_id, DIA, DIA)
    assert [t["celular"] for t in top] == [CELULAR]
    kardex = await lealtad_repository.listar_movimientos(conn, sucursal_id, CELULAR, DIA, DIA)
    assert len(kardex) == 1
    siguiente = DIA + timedelta(days=1)
    assert (
        await lealtad_repository.listar_movimientos(
            conn, sucursal_id, CELULAR, siguiente, siguiente
        )
        == []
    )
