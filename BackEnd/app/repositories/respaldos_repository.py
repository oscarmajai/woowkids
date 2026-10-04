from __future__ import annotations

from typing import Any

import asyncpg


async def ultimo(conn: asyncpg.Connection, *, exitoso: bool | None = None) -> dict[str, Any] | None:
    """El intento de respaldo terminado más reciente (o el más reciente
    exitoso) que dejó scripts/respaldos.py en la bitácora. Los que no tienen
    ``fin`` siguen en curso (o el proceso murió: lo cubre el aviso por
    antigüedad); un dump guarda su propia fila así, sin terminar."""
    filtro = "WHERE fin IS NOT NULL" + ("" if exitoso is None else " AND exitoso = $1")
    args: list[Any] = [] if exitoso is None else [exitoso]
    row = await conn.fetchrow(
        f"""
        SELECT inicio, fin, exitoso, motivo, nombre, tamano_bd, archivos, error
        FROM public.bitacora_respaldos
        {filtro}
        ORDER BY inicio DESC
        LIMIT 1
        """,
        *args,
    )
    return dict(row) if row else None
