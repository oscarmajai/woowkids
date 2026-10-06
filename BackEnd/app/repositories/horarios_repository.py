"""
app/repositories/horarios_repository.py
Operaciones de BD para el CRUD administrativo de horarios (tabla turnos).

``turnos.sucursal_id`` NULL = horario global (todas las sucursales lo
ven); con valor, el horario es solo de esa sucursal.
"""

from __future__ import annotations

import uuid
from datetime import time
from typing import Any, cast

import asyncpg

from app.core.utils import get_mexico_now


def _parse_time(t: str | None) -> time | None:
    if t is None:
        return None
    return time.fromisoformat(t)


def _fmt_time(t: object) -> str:
    """Convierte datetime.time a 'HH:MM'."""
    if hasattr(t, "strftime"):
        return cast(str, t.strftime("%H:%M"))
    return str(t)[:5]


_COLUMNAS = "id, nombre, hora_inicio, hora_fin, activo, dias, sucursal_id"


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["sucursal_id"] = str(d["sucursal_id"]) if d.get("sucursal_id") else None
    d["hora_inicio"] = _fmt_time(d["hora_inicio"])
    d["hora_fin"] = _fmt_time(d["hora_fin"])
    return d


async def listar_horarios(
    conn: asyncpg.Connection, sucursal_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Con sucursal: los de esa sucursal más los globales. Sin sucursal
    (AdministradorSistema en "Todas las sucursales"): todos."""
    rows = await conn.fetch(
        f"""
        SELECT {_COLUMNAS}
        FROM public.turnos
        WHERE $1::uuid IS NULL OR sucursal_id IS NULL OR sucursal_id = $1::uuid
        ORDER BY hora_inicio ASC, nombre ASC
        """,
        sucursal_id,
    )
    return [_row_to_dict(r) for r in rows]


async def existe_nombre(
    conn: asyncpg.Connection,
    nombre: str,
    sucursal_id: uuid.UUID | None,
    excluir_id: str | None = None,
) -> bool:
    """¿El nombre choca con otro horario visible junto a éste?

    Uno de sucursal no puede llamarse igual que otro de su sucursal ni que uno
    global (saldrían repetidos en la apertura de caja); uno global no puede
    llamarse igual que ningún otro."""
    return bool(
        await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1 FROM public.turnos
                WHERE nombre = $1
                  AND ($3::uuid IS NULL OR id <> $3::uuid)
                  AND ($2::uuid IS NULL OR sucursal_id IS NULL OR sucursal_id = $2::uuid)
            )
            """,
            nombre,
            sucursal_id,
            uuid.UUID(excluir_id) if excluir_id else None,
        )
    )


async def get_horario_por_id(conn: asyncpg.Connection, horario_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        f"""
        SELECT {_COLUMNAS}
        FROM public.turnos
        WHERE id = $1
        """,
        uuid.UUID(horario_id),
    )
    return _row_to_dict(row) if row else None


async def crear_horario(
    conn: asyncpg.Connection,
    nombre: str,
    hora_inicio: str,
    hora_fin: str,
    creado_por: str | None = None,
    dias: list[int] | None = None,
    sucursal_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    now = get_mexico_now()
    row = await conn.fetchrow(
        f"""
        INSERT INTO public.turnos
            (id, nombre, hora_inicio, hora_fin, dias, activo, creado, creado_por, sucursal_id)
        VALUES (gen_random_uuid(), $1, $2::time, $3::time, $4, TRUE, $5, $6, $7)
        RETURNING {_COLUMNAS}
        """,
        nombre,
        _parse_time(hora_inicio),
        _parse_time(hora_fin),
        dias,
        now,
        uuid.UUID(creado_por) if creado_por else None,
        sucursal_id,
    )
    return _row_to_dict(row)


async def actualizar_horario(
    conn: asyncpg.Connection,
    horario_id: str,
    nombre: str | None = None,
    hora_inicio: str | None = None,
    hora_fin: str | None = None,
    activo: bool | None = None,
    modificado_por: str | None = None,
    dias: list[int] | None = None,
    actualizar_dias: bool = False,
) -> dict[str, Any] | None:
    current = await get_horario_por_id(conn, horario_id)
    if current is None:
        return None

    now = get_mexico_now()
    row = await conn.fetchrow(
        f"""
        UPDATE public.turnos
        SET
            nombre      = COALESCE($2, nombre),
            hora_inicio = COALESCE($3::time, hora_inicio),
            hora_fin    = COALESCE($4::time, hora_fin),
            activo      = COALESCE($5, activo),
            dias        = CASE WHEN $7 THEN $6 ELSE dias END,
            modificado  = $8,
            modificado_por = $9
        WHERE id = $1
        RETURNING {_COLUMNAS}
        """,
        uuid.UUID(horario_id),
        nombre,
        _parse_time(hora_inicio),
        _parse_time(hora_fin),
        activo,
        dias,
        actualizar_dias,
        now,
        uuid.UUID(modificado_por) if modificado_por else None,
    )
    return _row_to_dict(row) if row else None


async def eliminar_horario(
    conn: asyncpg.Connection,
    horario_id: str,
    modificado_por: str | None = None,
) -> bool:
    """Borrado lógico: activo = FALSE. Devuelve True si la fila existía."""
    now = get_mexico_now()
    result = await conn.execute(
        """
        UPDATE public.turnos
        SET activo = FALSE, modificado = $2, modificado_por = $3
        WHERE id = $1
        """,
        uuid.UUID(horario_id),
        now,
        uuid.UUID(modificado_por) if modificado_por else None,
    )
    return bool(result != "UPDATE 0")
