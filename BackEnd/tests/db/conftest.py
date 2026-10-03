"""Fixtures para pruebas de concurrencia contra un PostgreSQL REAL y desechable.

Nunca se usa la BD compartida de desarrollo (DATABASE_URL): todo corre contra
`TEST_DATABASE_URL`, que debe apuntar a una BD de prueba con
`sql/schema_maestro.sql` cargado. Si la variable no existe, todos los tests de
esta carpeta se saltan. Cada test crea sus propios datos con nombres únicos, así
que se pueden correr varias veces sobre la misma BD sin limpiarla.

Ejemplo:
    docker run -d --name wk-pg -e POSTGRES_USER=dev -e POSTGRES_PASSWORD=dev \\
        -e POSTGRES_DB=woowkids -p 0:5432 postgres:16-alpine
    docker exec -i wk-pg psql -U dev -d woowkids < sql/schema_maestro.sql
    TEST_DATABASE_URL=postgresql://dev:dev@localhost:<puerto>/woowkids pytest tests/db -q
"""

import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Settings() se instancia al importar los services: le damos valores mínimos.
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL or "postgresql://u:p@localhost:5432/x")
os.environ.setdefault("MINIO_ACCESS_KEY", "test-access-key")
os.environ.setdefault("MINIO_SECRET_KEY", "test-secret-key")

import asyncpg  # noqa: E402
import pytest_asyncio  # noqa: E402

# Cuántas peticiones simultáneas lanza cada prueba de carrera.
N_CONCURRENTES = 8


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL no está definida")
    for item in items:
        if "tests/db/" in str(item.fspath).replace(os.sep, "/"):
            item.add_marker(skip)


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[asyncpg.Pool]:
    assert TEST_DATABASE_URL
    p = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=N_CONCURRENTES + 2, max_size=20)
    try:
        yield p
    finally:
        await p.close()


@dataclass
class Escenario:
    sucursal_id: uuid.UUID
    usuario_id: uuid.UUID


@pytest_asyncio.fixture
async def escenario(pool: asyncpg.Pool) -> Escenario:
    """Sucursal + usuario cajero nuevos, con nombres únicos."""
    sufijo = uuid.uuid4().hex[:10]
    async with pool.acquire() as conn:
        sucursal_id = await conn.fetchval(
            "INSERT INTO public.sucursales (nombre) VALUES ($1) RETURNING id",
            f"Sucursal carrera {sufijo}",
        )
        usuario_id = await conn.fetchval(
            """
            INSERT INTO public.usuarios (email, password_hash, nombre_completo, rol)
            VALUES ($1, 'x', $2, 3) RETURNING id
            """,
            f"cajero.{sufijo}@test.local",
            f"Cajero {sufijo}",
        )
    return Escenario(sucursal_id=sucursal_id, usuario_id=usuario_id)


async def crear_apertura(
    pool: asyncpg.Pool, esc: Escenario, fondo_inicial: Decimal, estado: str = "ABIERTA"
) -> str:
    """Caja + turno + apertura propia del escenario. Devuelve el id de la apertura."""
    sufijo = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        caja_id = await conn.fetchval(
            "INSERT INTO public.cajas (sucursal_id, codigo, nombre) VALUES ($1, $2, $3) "
            "RETURNING id",
            esc.sucursal_id,
            f"C-{sufijo}",
            f"Caja {sufijo}",
        )
        turno_id = await conn.fetchval(
            "INSERT INTO public.turnos (nombre, hora_inicio, hora_fin) "
            "VALUES ($1, '08:00', '16:00') RETURNING id",
            f"Turno {sufijo}",
        )
        apertura_id = await conn.fetchval(
            """
            INSERT INTO public.apertura_caja (caja_id, cajero_id, turno_id, fondo_inicial, estado)
            VALUES ($1, $2, $3, $4, $5) RETURNING id
            """,
            caja_id,
            esc.usuario_id,
            turno_id,
            fondo_inicial,
            estado,
        )
    return str(apertura_id)
