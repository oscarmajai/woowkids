from __future__ import annotations

from datetime import datetime
from uuid import UUID

import asyncpg


async def revoke_token(conn: asyncpg.Connection, jti: str, expires_at: datetime) -> None:
    await conn.execute(
        """
        INSERT INTO public.tokens_revocados (jti, expires_at)
        VALUES ($1, $2)
        ON CONFLICT (jti) DO NOTHING
        """,
        UUID(jti),
        expires_at,
    )


async def is_token_revoked(conn: asyncpg.Connection, jti: str) -> bool:
    row = await conn.fetchrow(
        "SELECT 1 FROM public.tokens_revocados WHERE jti = $1",
        UUID(jti),
    )
    return row is not None


async def get_estado_sesion(
    conn: asyncpg.Connection, jti: str, usuario_id: UUID | None
) -> tuple[bool, bool]:
    """A11: en una sola consulta, si el token está revocado y si su usuario
    existe y sigue activo. ``usuario_id=None`` (sesión de padre, cuyo ``sub``
    no es un usuario) no consulta usuarios y lo da por activo."""
    row = await conn.fetchrow(
        """
        SELECT
            EXISTS (SELECT 1 FROM public.tokens_revocados WHERE jti = $1) AS revocado,
            ($2::uuid IS NULL OR EXISTS (
                SELECT 1 FROM public.usuarios WHERE id = $2 AND activo = TRUE
            )) AS usuario_activo
        """,
        UUID(jti),
        usuario_id,
    )
    return bool(row["revocado"]), bool(row["usuario_activo"])


async def cleanup_expired_tokens(conn: asyncpg.Connection) -> None:
    """Elimina entradas de tokens cuya expiración ya pasó. Llamar periódicamente."""
    await conn.execute("DELETE FROM public.tokens_revocados WHERE expires_at < NOW()")
