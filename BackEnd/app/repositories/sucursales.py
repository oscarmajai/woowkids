from datetime import datetime
from uuid import UUID

import asyncpg


async def exists_sucursal(conn: asyncpg.Connection, sucursal_id: UUID) -> bool:
    result = await conn.fetchval(
        """
       SELECT EXISTS(
           SELECT 1
           FROM sucursales
           WHERE id = $1
       )
       """,
        sucursal_id,
    )
    return bool(result)


async def ahora_en_sucursal(conn: asyncpg.Connection, sucursal_id: UUID) -> datetime | None:
    """Fecha y hora actuales en la zona horaria de la sucursal (`zona_horaria`),
    sin zona (hora de pared local). None si la sucursal no existe.

    La conversión la hace PostgreSQL: la imagen del backend no trae la base de
    zonas horarias del sistema que necesitaría `zoneinfo`."""
    ahora: datetime | None = await conn.fetchval(
        "SELECT (NOW() AT TIME ZONE zona_horaria) FROM public.sucursales WHERE id = $1",
        sucursal_id,
    )
    return ahora


async def a_hora_local(
    conn: asyncpg.Connection, sucursal_id: UUID, momento: datetime
) -> datetime | None:
    """Convierte un instante con zona a la hora de pared de la sucursal (sin zona)."""
    local: datetime | None = await conn.fetchval(
        "SELECT ($2::timestamptz AT TIME ZONE zona_horaria) FROM public.sucursales WHERE id = $1",
        sucursal_id,
        momento,
    )
    return local
