from collections.abc import AsyncGenerator

import asyncpg
from fastapi import HTTPException, status

from app.core.config import settings

_pool: asyncpg.Pool | None = None

_SIN_CONEXIONES = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail={
        "code": "SERVICE_UNAVAILABLE",
        "message": "El sistema está ocupado en este momento. Intenta de nuevo en unos segundos.",
    },
)


async def create_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        command_timeout=settings.db_command_timeout,
    )


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("El pool de base de datos no está inicializado")
    return _pool


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """Conexión del pool para una petición HTTP; se devuelve al terminarla.

    No usar en endpoints WebSocket: la dependencia vive lo que dura la conexión
    del navegador y retendría la conexión a la BD todo ese tiempo (con unas
    cuantas pantallas abiertas se agotaba el pool y se colgaba toda la API). Ahí
    se usa ``conexion_breve``."""
    pool = get_pool()
    try:
        conn = await pool.acquire(timeout=settings.db_pool_acquire_timeout)
    except TimeoutError:
        raise _SIN_CONEXIONES from None
    try:
        yield conn
    finally:
        await pool.release(conn)


def conexion_breve() -> "asyncpg.pool.PoolAcquireContext":
    """``async with conexion_breve() as conn:`` para usar la BD un momento y
    soltarla de inmediato (handshake de WebSocket, tareas en segundo plano)."""
    return get_pool().acquire(timeout=settings.db_pool_acquire_timeout)
