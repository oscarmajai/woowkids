"""Códigos de acceso del portal de padres (migración 076). Solo se
guarda el sha256 del código; el código en claro existe únicamente en la
respuesta del registro de entrada y en el QR impreso."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg


async def crear_codigo(
    conn: asyncpg.Connection,
    registro_id: UUID,
    codigo_hash: str,
    expira: datetime,
    creado_por: UUID | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO public.codigos_acceso_padres (registro_id, codigo_hash, expira, creado_por)
        VALUES ($1, $2, $3, $4)
        """,
        registro_id,
        codigo_hash,
        expira,
        creado_por,
    )


async def revocar_codigos_de_registro(conn: asyncpg.Connection, registro_id: UUID) -> None:
    """Revoca todos los códigos vigentes del registro (checkout del último
    niño o emisión de un código nuevo)."""
    await conn.execute(
        """
        UPDATE public.codigos_acceso_padres
        SET revocado = NOW()
        WHERE registro_id = $1 AND revocado IS NULL
        """,
        registro_id,
    )


async def get_registro_por_codigo(
    conn: asyncpg.Connection, codigo_hash: str
) -> dict[str, Any] | None:
    """Registro al que da acceso un código vigente: no revocado, no expirado
    y con el registro todavía activo. None en cualquier otro caso."""
    row = await conn.fetchrow(
        """
        SELECT r.id AS "registroId",
               r.tutores_id AS "tutorId",
               r.sucursal_id AS "sucursalId",
               c.expira
        FROM public.codigos_acceso_padres c
        JOIN public.registros r ON r.id = c.registro_id
        WHERE c.codigo_hash = $1
          AND c.revocado IS NULL
          AND c.expira > NOW()
          AND r.activo = TRUE
          AND r.estado = 'A'
        """,
        codigo_hash,
    )
    return dict(row) if row else None
