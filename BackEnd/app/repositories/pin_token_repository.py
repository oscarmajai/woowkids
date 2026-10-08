"""
app/repositories/pin_token_repository.py
Tokens de un solo uso emitidos al validar el PIN de cajero/administrador.
Cada token guarda su propósito: ``cerrar`` para el cierre de
caja (POST /turnos-caja/confirmar exige uno de cada rol) y ``cancelar`` para
cancelaciones y devoluciones de órdenes cobradas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncpg

_INSERT = """
    INSERT INTO public.pin_tokens (token, usuario_id, turno_id, rol, proposito, expira)
    VALUES ($1, $2, $3, $4, $5, $6)
"""

_SELECT_VALIDO = """
    SELECT token, usuario_id, turno_id, rol, proposito, expira, usado
    FROM public.pin_tokens
    WHERE token = $1 AND turno_id = $2 AND rol = $3
"""

_MARCAR_USADO = """
    UPDATE public.pin_tokens SET usado = TRUE WHERE token = $1
"""


async def crear_token(
    conn: asyncpg.Connection,
    token: str,
    usuario_id: str,
    turno_id: str,
    rol: str,
    proposito: str,
    expira: datetime,
) -> None:
    await conn.execute(_INSERT, token, usuario_id, turno_id, rol, proposito, expira)


async def obtener_token(
    conn: asyncpg.Connection, token: str, turno_id: str, rol: str
) -> dict[str, Any] | None:
    row = await conn.fetchrow(_SELECT_VALIDO, token, turno_id, rol)
    return dict(row) if row else None


async def marcar_usado(conn: asyncpg.Connection, token: str) -> None:
    await conn.execute(_MARCAR_USADO, token)
