"""Intentos fallidos de PIN de caja (A16, migración 081).

La llave del límite es (usuario dueño del PIN, sucursal). Todas las funciones
asumen que el llamador ya está dentro de ``conn.transaction()`` y que tomó el
candado de esa llave con ``bloquear_llave``: así dos workers que validan el
mismo PIN al mismo tiempo no ven el mismo conteo y no se pasan del límite.
"""

from __future__ import annotations

import uuid

import asyncpg


def _uuid(valor: str | uuid.UUID | None) -> uuid.UUID | None:
    if valor is None:
        return None
    return valor if isinstance(valor, uuid.UUID) else uuid.UUID(str(valor))


async def bloquear_llave(
    conn: asyncpg.Connection, usuario_id: str | uuid.UUID, sucursal_id: str | uuid.UUID | None
) -> None:
    """Candado de transacción por (usuario, sucursal). Se libera al confirmar."""
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
        f"intentos_pin:{_uuid(usuario_id)}:{_uuid(sucursal_id) or '-'}",
    )


async def segundos_de_bloqueo(
    conn: asyncpg.Connection,
    usuario_id: str | uuid.UUID,
    sucursal_id: str | uuid.UUID | None,
    max_fallos: int,
    ventana_minutos: int,
) -> int:
    """0 si quedan intentos; si no, los segundos que faltan para que el más
    viejo de los últimos ``max_fallos`` fallos salga de la ventana."""
    valor = await conn.fetchval(
        """
        WITH recientes AS (
            SELECT creado
            FROM public.intentos_pin_fallidos
            WHERE usuario_id = $1
              AND sucursal_id IS NOT DISTINCT FROM $2
              AND creado > NOW() - make_interval(mins => $4)
            ORDER BY creado DESC
            LIMIT $3
        )
        SELECT CASE
            WHEN COUNT(*) < $3 THEN 0
            ELSE GREATEST(
                1,
                CEIL(EXTRACT(EPOCH FROM (
                    MIN(creado) + make_interval(mins => $4) - NOW()
                )))::int
            )
        END
        FROM recientes
        """,
        _uuid(usuario_id),
        _uuid(sucursal_id),
        max_fallos,
        ventana_minutos,
    )
    return int(valor or 0)


async def registrar_fallo(
    conn: asyncpg.Connection,
    usuario_id: str | uuid.UUID,
    sucursal_id: str | uuid.UUID | None,
    tipo: str,
    intentado_por: str | uuid.UUID | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO public.intentos_pin_fallidos (usuario_id, sucursal_id, tipo, intentado_por)
        VALUES ($1, $2, $3, $4)
        """,
        _uuid(usuario_id),
        _uuid(sucursal_id),
        tipo,
        _uuid(intentado_por),
    )


async def limpiar(
    conn: asyncpg.Connection, usuario_id: str | uuid.UUID, sucursal_id: str | uuid.UUID | None
) -> None:
    """Un acierto reinicia el contador de esa llave."""
    await conn.execute(
        """
        DELETE FROM public.intentos_pin_fallidos
        WHERE usuario_id = $1 AND sucursal_id IS NOT DISTINCT FROM $2
        """,
        _uuid(usuario_id),
        _uuid(sucursal_id),
    )


async def purgar_viejos(conn: asyncpg.Connection, usuario_id: str | uuid.UUID) -> None:
    """Borra los fallos de más de un día del usuario para que la tabla no crezca."""
    await conn.execute(
        """
        DELETE FROM public.intentos_pin_fallidos
        WHERE usuario_id = $1 AND creado < NOW() - INTERVAL '1 day'
        """,
        _uuid(usuario_id),
    )
