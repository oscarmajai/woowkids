from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import asyncpg

_SELECT = """
    SELECT id, reservacion_id, extra_id, cantidad, precio_unitario, subtotal, creado, creado_por
    FROM reservacion_extras
"""


async def listar_por_reservacion(
    conn: asyncpg.Connection, reservacion_id: UUID
) -> list[dict[str, Any]]:
    rows = await conn.fetch(_SELECT + " WHERE reservacion_id = $1", reservacion_id)
    return [dict(r) for r in rows]


async def listar_con_unidad_por_reservacion(
    conn: asyncpg.Connection, reservacion_id: UUID
) -> list[dict[str, Any]]:
    """Extras de la reservación con la `unidad` de su catálogo, para recalcular
    la cantidad de los que se cobran por persona o por hora (M15)."""
    rows = await conn.fetch(
        """
        SELECT re.id, re.extra_id, re.cantidad, re.precio_unitario, e.unidad
        FROM public.reservacion_extras re
        LEFT JOIN public.extras e ON e.id = re.extra_id
        WHERE re.reservacion_id = $1
        """,
        reservacion_id,
    )
    return [dict(r) for r in rows]


async def obtener(conn: asyncpg.Connection, reservacion_extra_id: UUID) -> dict[str, Any] | None:
    row = await conn.fetchrow(_SELECT + " WHERE id = $1", reservacion_extra_id)
    return dict(row) if row else None


async def crear(
    conn: asyncpg.Connection,
    reservacion_id: UUID,
    extra_id: UUID,
    cantidad: int,
    precio_unitario: Decimal,
    creado_por: UUID | None = None,
) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        INSERT INTO reservacion_extras
            (reservacion_id, extra_id, cantidad, precio_unitario, creado_por)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, reservacion_id, extra_id, cantidad, precio_unitario, subtotal,
                  creado, creado_por
        """,
        reservacion_id,
        extra_id,
        cantidad,
        precio_unitario,
        creado_por,
    )
    return dict(row)


async def actualizar(
    conn: asyncpg.Connection, reservacion_extra_id: UUID, updates: dict[str, Any]
) -> dict[str, Any] | None:
    if not updates:
        return await obtener(conn, reservacion_extra_id)
    set_parts = [f"{k} = ${i + 2}" for i, k in enumerate(updates)]
    sql = (
        f"UPDATE reservacion_extras SET {', '.join(set_parts)} WHERE id = $1 "
        "RETURNING id, reservacion_id, extra_id, cantidad, precio_unitario, subtotal, "
        "creado, creado_por"
    )
    row = await conn.fetchrow(sql, reservacion_extra_id, *updates.values())
    return dict(row) if row else None


async def eliminar(conn: asyncpg.Connection, reservacion_extra_id: UUID) -> bool:
    result = await conn.execute(
        "DELETE FROM reservacion_extras WHERE id = $1", reservacion_extra_id
    )
    return bool(result == "DELETE 1")


async def total_por_reservacion(conn: asyncpg.Connection, reservacion_id: UUID) -> Decimal:
    """Suma de los subtotales de los extras de la reservación (su `precio_extras`)."""
    total = await conn.fetchval(
        "SELECT COALESCE(SUM(subtotal), 0) FROM public.reservacion_extras "
        "WHERE reservacion_id = $1",
        reservacion_id,
    )
    return cast(Decimal, total)
