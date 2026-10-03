"""M9 contra PostgreSQL real: no se desactiva una caja con turno abierto, y
una caja desactivada ya no abre turnos."""

import uuid
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio
from app.api.routers import cajas_admin
from app.repositories import caja_repository
from app.schemas.auth import TokenData
from fastapi import HTTPException

from tests.db.pos_fixtures import Pos, crear_pos


@pytest_asyncio.fixture
async def pos(pool: asyncpg.Pool) -> Pos:
    return await crear_pos(pool)


# ── M9 ────────────────────────────────────────────────────────────────────────


def _admin(sucursal: uuid.UUID, usuario: uuid.UUID) -> TokenData:
    return TokenData(
        sub=str(usuario),
        email="admin@test.local",
        role="Administrador",
        branch_id=sucursal,
        jti="jti",
        exp=datetime(2099, 1, 1, tzinfo=UTC),
    )


async def test_no_se_desactiva_una_caja_con_turno_abierto(pool: asyncpg.Pool, pos: Pos) -> None:
    async with pool.acquire() as conn:
        with pytest.raises(HTTPException) as exc_info:
            await cajas_admin.eliminar(str(pos.caja), _admin(pos.sucursal, pos.cajero), conn)
        activa = await conn.fetchval("SELECT activo FROM public.cajas WHERE id = $1", pos.caja)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "CAJA_CON_TURNO_ABIERTO"
    assert activa is True


async def test_caja_sin_turno_se_desactiva_y_ya_no_abre_turnos(
    pool: asyncpg.Pool, pos: Pos
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.apertura_caja SET estado = 'CERRADA' WHERE id = $1",
            uuid.UUID(pos.apertura),
        )
        await cajas_admin.eliminar(str(pos.caja), _admin(pos.sucursal, pos.cajero), conn)
        activa = await conn.fetchval("SELECT activo FROM public.cajas WHERE id = $1", pos.caja)
        por_id = await caja_repository.get_caja_por_id(conn, str(pos.sucursal), str(pos.caja))
        codigo = await conn.fetchval("SELECT codigo FROM public.cajas WHERE id = $1", pos.caja)
        por_codigo = await caja_repository.get_caja_por_codigo(conn, str(pos.sucursal), codigo)

    assert activa is False
    assert por_id is None
    assert por_codigo is None
