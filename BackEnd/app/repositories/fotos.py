from enum import Enum
from typing import Any
from uuid import UUID

import asyncpg


class TipoFoto(str, Enum):
    INE = "I"
    LLEGADA = "L"


async def foto_create(
    conn: asyncpg.Connection,
    registro_id: UUID,
    tipo: TipoFoto,
    storage_url: str,
    usuario_id: UUID,
    id: UUID | None = None,
) -> None:
    if id is None:
        await conn.execute(
            """
            INSERT INTO fotos (
                registro_id,
                tipo,
                storage_url,
                creado,
                creado_por
            )
            VALUES ($1, $2, $3, NOW(), $4)
            """,
            registro_id,
            tipo,
            storage_url,
            usuario_id,
        )
    else:
        await conn.execute(
            """
            INSERT INTO fotos (
                id,
                registro_id,
                tipo,
                storage_url,
                creado,
                creado_por
            )
            VALUES ($1, $2, $3, $4, NOW(), $5)
            """,
            id,
            registro_id,
            tipo,
            storage_url,
            usuario_id,
        )


async def get_fotos_llegada_by_registro_id(
    conn: asyncpg.Connection,
    registro_id: UUID,
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT storage_url
        FROM fotos
        WHERE registro_id = $1 AND tipo = $2
        """,
        registro_id,
        TipoFoto.LLEGADA.value,
    )
    return [dict(row) for row in rows]


async def get_registro_id_by_foto_ine(
    conn: asyncpg.Connection,
    storage_url: str,
) -> UUID | None:
    """registro_id dueño de la foto de INE guardada en storage_url, o None si
    no hay una INE activa con esa ruta (C6: la descarga se autoriza por el
    registro, no por el nombre del archivo)."""
    registro_id: UUID | None = await conn.fetchval(
        """
        SELECT registro_id
        FROM fotos
        WHERE storage_url = $1 AND tipo = $2 AND activo = TRUE
        LIMIT 1
        """,
        storage_url,
        TipoFoto.INE.value,
    )
    return registro_id
