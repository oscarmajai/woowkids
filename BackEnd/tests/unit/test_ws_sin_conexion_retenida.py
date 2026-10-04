"""Bloqueante de entrega: cada WebSocket abierto retenía una conexión del pool
de BD mientras durara (Depends(get_db) en el endpoint). Con unas cuantas
pantallas de caja, cocina y control de acceso abiertas se agotaba el pool y
toda la API se quedaba esperando sin límite."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core import database
from app.core.database import get_db
from fastapi import HTTPException
from fastapi.routing import APIWebSocketRoute


def _dependencias(dependant):
    pila = list(dependant.dependencies)
    while pila:
        dep = pila.pop()
        yield dep
        pila.extend(dep.dependencies)


def test_ningun_websocket_retiene_una_conexion_de_bd():
    from app.main import app

    rutas_ws = [r for r in app.routes if isinstance(r, APIWebSocketRoute)]
    assert {r.path for r in rutas_ws} >= {"/api/comandas/ws", "/api/estancias/ws"}
    for ruta in rutas_ws:
        assert all(d.call is not get_db for d in _dependencias(ruta.dependant)), ruta.path


@pytest.mark.asyncio
async def test_sin_conexiones_libres_responde_503_en_vez_de_colgarse():
    pool = MagicMock()
    pool.acquire = AsyncMock(side_effect=TimeoutError)
    with patch.object(database, "_pool", pool):
        with pytest.raises(HTTPException) as exc:
            await anext(get_db())
    assert exc.value.status_code == 503
    assert pool.acquire.await_args.kwargs["timeout"] > 0


@pytest.mark.asyncio
async def test_get_db_devuelve_la_conexion_al_pool():
    conn = object()
    pool = MagicMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    with patch.object(database, "_pool", pool):
        gen = get_db()
        assert await anext(gen) is conn
        with pytest.raises(StopAsyncIteration):
            await anext(gen)
    pool.release.assert_awaited_once_with(conn)
