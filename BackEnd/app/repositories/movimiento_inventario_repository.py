"""
app/repositories/movimiento_inventario_repository.py
Única capa que habla con la BD para el ledger de movimientos de inventario —
SQL crudo con asyncpg. Regla 11.1 y 11.4 SAD. Tabla append-only: no hay
`actualizar` ni `eliminar` aquí, solo `registrar` + lecturas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

_SELECT = """
    SELECT mi.id, mi.sucursal_id, mi.insumo_id, mi.tipo, mi.cantidad, mi.stock_resultante,
           mi.motivo, mi.referencia_id, mi.notas, mi.costo_total, mi.creado, mi.creado_por,
           i.nombre AS insumo_nombre
    FROM public.movimientos_inventario mi
    JOIN public.insumos i ON i.id = mi.insumo_id
"""

# Zona horaria de la sucursal $1 / de la sucursal del insumo $1.
_ZONA_SUCURSAL = "(SELECT s.zona_horaria FROM public.sucursales s WHERE s.id = $1)"
_ZONA_INSUMO = (
    "(SELECT s.zona_horaria FROM public.insumos ins "
    "JOIN public.sucursales s ON s.id = ins.sucursal_id WHERE ins.id = $1)"
)


def _desde_local(columna: str, idx: int, zona: str) -> str:
    """`columna` desde el inicio del día $idx en la zona de la sucursal (M4)."""
    return f"{columna} >= (${idx}::date::timestamp AT TIME ZONE {zona})"


def _hasta_local(columna: str, idx: int, zona: str) -> str:
    """`columna` hasta el fin del día $idx (inclusivo) en la zona de la sucursal (M4)."""
    return f"{columna} < ((${idx}::date + 1)::timestamp AT TIME ZONE {zona})"


async def registrar(
    conn: asyncpg.Connection,
    *,
    sucursal_id: UUID,
    insumo_id: UUID,
    tipo: str,
    cantidad: Decimal,
    stock_resultante: Decimal,
    motivo: str,
    referencia_id: UUID | None,
    notas: str | None,
    creado_por: UUID | None,
    costo_total: Decimal | None = None,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO public.movimientos_inventario
            (sucursal_id, insumo_id, tipo, cantidad, stock_resultante, motivo,
             referencia_id, notas, creado_por, costo_total)
        VALUES ($1, $2, $3, $4, $5, $6::motivo_movimiento_inventario, $7, $8, $9, $10)
        RETURNING id
        """,
        sucursal_id,
        insumo_id,
        tipo,
        cantidad,
        stock_resultante,
        motivo,
        referencia_id,
        notas,
        creado_por,
        costo_total,
    )
    movimiento_id: UUID = row["id"]
    return movimiento_id


async def obtener(conn: asyncpg.Connection, movimiento_id: UUID) -> dict[str, Any] | None:
    row = await conn.fetchrow(_SELECT + " WHERE mi.id = $1", movimiento_id)
    return dict(row) if row else None


async def costo_unitario_venta(
    conn: asyncpg.Connection, comanda_id: UUID, insumo_id: UUID
) -> Decimal | None:
    """Costo unitario al que salió un insumo en una comanda (para revertirlo al
    mismo costo si se cancela). Promedia todos los movimientos 'S' de esa
    comanda para ese insumo. None si no hay dato de costo."""
    valor = await conn.fetchval(
        """
        SELECT SUM(costo_total) / NULLIF(SUM(cantidad), 0)
        FROM public.movimientos_inventario
        WHERE referencia_id = $1 AND insumo_id = $2
          AND motivo = 'venta_comanda' AND costo_total IS NOT NULL
        """,
        comanda_id,
        insumo_id,
    )
    return Decimal(str(valor)) if valor is not None else None


async def listar_por_insumo(
    conn: asyncpg.Connection,
    insumo_id: UUID,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[dict[str, Any]]:
    """Historial de movimientos de un insumo (kardex), opcionalmente acotado
    a un rango de fechas. `hasta` es inclusivo del día completo; los días son
    los de la zona horaria de la sucursal del insumo."""
    conditions = ["mi.insumo_id = $1"]
    params: list[Any] = [insumo_id]
    if desde is not None:
        params.append(desde)
        conditions.append(_desde_local("mi.creado", len(params), _ZONA_INSUMO))
    if hasta is not None:
        params.append(hasta)
        conditions.append(_hasta_local("mi.creado", len(params), _ZONA_INSUMO))

    where_clause = " AND ".join(conditions)
    rows = await conn.fetch(_SELECT + f" WHERE {where_clause} ORDER BY mi.creado DESC", *params)
    return [dict(r) for r in rows]


async def reporte_cogs(
    conn: asyncpg.Connection,
    sucursal_id: UUID,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[dict[str, Any]]:
    """Costo de lo consumido (salidas de venta + mermas) por insumo en el
    periodo. `hasta` inclusivo del día completo, en la zona de la sucursal."""
    conditions = ["mi.sucursal_id = $1", "mi.tipo IN ('S', 'M')"]
    params: list[Any] = [sucursal_id]
    if desde is not None:
        params.append(desde)
        conditions.append(_desde_local("mi.creado", len(params), _ZONA_SUCURSAL))
    if hasta is not None:
        params.append(hasta)
        conditions.append(_hasta_local("mi.creado", len(params), _ZONA_SUCURSAL))

    where_clause = " AND ".join(conditions)
    rows = await conn.fetch(
        f"""
        SELECT mi.insumo_id, i.nombre AS insumo_nombre,
               SUM(mi.cantidad) AS cantidad_salida,
               COALESCE(SUM(mi.costo_total), 0) AS costo_total
        FROM public.movimientos_inventario mi
        JOIN public.insumos i ON i.id = mi.insumo_id
        WHERE {where_clause}
        GROUP BY mi.insumo_id, i.nombre
        ORDER BY costo_total DESC, i.nombre ASC
        """,
        *params,
    )
    return [dict(r) for r in rows]


async def resumen_costo_ventas(
    conn: asyncpg.Connection,
    sucursal_id: UUID,
    desde: date | None = None,
    hasta: date | None = None,
) -> dict[str, Any]:
    """KPIs del reporte de costo de ventas (B7 pendiente #3): ventas totales
    de comandas en el periodo, costo de lo vendido (motivo venta_comanda),
    margen (ventas - costo) y merma (motivo merma, por separado del costo
    de venta).

    Las comandas canceladas (`estado_actual = 'C'` o `activo = FALSE`) no
    cuentan como venta, y al costo de lo vendido se le resta lo que su
    cancelación devolvió al inventario (A3). Los días son los de la zona
    horaria de la sucursal (M4)."""
    conditions_mov = ["mi.sucursal_id = $1"]
    conditions_com = ["c.sucursal_id = $1", "c.estado_actual <> 'C'", "c.activo"]
    params: list[Any] = [sucursal_id]
    if desde is not None:
        params.append(desde)
        idx = len(params)
        conditions_mov.append(_desde_local("mi.creado", idx, _ZONA_SUCURSAL))
        conditions_com.append(_desde_local("c.fecha_hora", idx, _ZONA_SUCURSAL))
    if hasta is not None:
        params.append(hasta)
        idx = len(params)
        conditions_mov.append(_hasta_local("mi.creado", idx, _ZONA_SUCURSAL))
        conditions_com.append(_hasta_local("c.fecha_hora", idx, _ZONA_SUCURSAL))

    where_mov = " AND ".join(conditions_mov)
    where_com = " AND ".join(conditions_com)

    # La devolución por cancelación se descuenta en el periodo de la venta
    # original, igual que la venta deja de contarse en ese periodo.
    costo_venta_row = await conn.fetchrow(
        f"""
        WITH vendidos AS (
            SELECT mi.referencia_id, mi.costo_total
            FROM public.movimientos_inventario mi
            WHERE {where_mov} AND mi.motivo = 'venta_comanda'
        )
        SELECT COALESCE((SELECT SUM(costo_total) FROM vendidos), 0)
             - COALESCE((
                   SELECT SUM(d.costo_total)
                   FROM public.movimientos_inventario d
                   WHERE d.sucursal_id = $1
                     AND d.motivo = 'cancelacion_comanda'
                     AND d.referencia_id IN (SELECT referencia_id FROM vendidos)
               ), 0) AS costo_ventas
        """,
        *params,
    )
    merma_row = await conn.fetchrow(
        f"""
        SELECT COALESCE(SUM(mi.costo_total), 0) AS merma
        FROM public.movimientos_inventario mi
        WHERE {where_mov} AND mi.motivo = 'merma'
        """,
        *params,
    )
    ventas_row = await conn.fetchrow(
        f"""
        SELECT COALESCE(SUM(c.total_final), 0) AS ventas_totales
        FROM public.comandas c
        WHERE {where_com}
        """,
        *params,
    )
    costo_ventas = Decimal(str(costo_venta_row["costo_ventas"]))
    merma = Decimal(str(merma_row["merma"]))
    ventas_totales = Decimal(str(ventas_row["ventas_totales"]))
    return {
        "ventas_totales": ventas_totales,
        "costo_ventas": costo_ventas,
        "margen": ventas_totales - costo_ventas,
        "merma": merma,
    }
