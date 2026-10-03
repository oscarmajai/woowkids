"""
app/repositories/devolucion_repository.py
Devoluciones al cliente por la cancelación de una comanda cobrada (A4) y los
cobros de caja de esa comanda que se devuelven.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import asyncpg

# Cobros ('O') y cambio entregado ('C') que la venta registró en caja. El
# método NULL es la venta de POST /comandas, que el arqueo cuenta como
# efectivo (caja_repository.sumar_ventas_efectivo_apertura).
_SELECT_MOVIMIENTOS_VENTA = """
    SELECT
        m.apertura_caja_id,
        a.estado            AS apertura_estado,
        m.tipo_movimiento::text AS tipo_movimiento,
        m.metodo_pago_id,
        (m.metodo_pago_id IS NULL OR mp.tipo = 'E') AS es_efectivo,
        m.monto
    FROM public.movimientos_caja m
    JOIN public.apertura_caja a ON a.id = m.apertura_caja_id
    LEFT JOIN public.metodos_pago mp ON mp.id = m.metodo_pago_id
    WHERE m.referencia_id = $1
      AND m.tipo_movimiento IN ('O', 'C')
    ORDER BY m.id
"""

_EXISTE_PAGO_ORDEN = """
    SELECT EXISTS (
        SELECT 1 FROM public.pagos_ordenes
        WHERE comanda_id = $1 AND activo = TRUE AND monto > 0
    )
"""

_INSERT = """
    INSERT INTO public.devoluciones_comanda
        (comanda_id, apertura_caja_id, apertura_venta_id, metodo_pago_id,
         es_efectivo, monto, autorizado_por, creado_por)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    RETURNING id
"""

_LISTAR_POR_APERTURA = """
    SELECT d.id, d.comanda_id, c.ticket_numero, d.metodo_pago_id,
           mp.nombre AS metodo_pago_nombre, d.es_efectivo, d.monto,
           d.autorizado_por, u.nombre_completo AS autorizado_por_nombre, d.creado
    FROM public.devoluciones_comanda d
    JOIN public.comandas c ON c.id = d.comanda_id
    LEFT JOIN public.metodos_pago mp ON mp.id = d.metodo_pago_id
    LEFT JOIN public.usuarios u ON u.id = d.autorizado_por
    WHERE d.apertura_caja_id = $1
    ORDER BY d.creado DESC
"""


async def movimientos_venta(conn: asyncpg.Connection, comanda_id: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(_SELECT_MOVIMIENTOS_VENTA, uuid.UUID(comanda_id))
    return [dict(r) for r in rows]


async def tiene_pagos_orden(conn: asyncpg.Connection, comanda_id: str) -> bool:
    return bool(await conn.fetchval(_EXISTE_PAGO_ORDEN, uuid.UUID(comanda_id)))


async def registrar(
    conn: asyncpg.Connection,
    *,
    comanda_id: str,
    apertura_caja_id: str,
    apertura_venta_id: str | None,
    metodo_pago_id: str | None,
    es_efectivo: bool,
    monto: Decimal,
    autorizado_por: str,
    creado_por: str,
) -> str:
    devolucion_id = await conn.fetchval(
        _INSERT,
        uuid.UUID(comanda_id),
        uuid.UUID(apertura_caja_id),
        uuid.UUID(apertura_venta_id) if apertura_venta_id else None,
        uuid.UUID(metodo_pago_id) if metodo_pago_id else None,
        es_efectivo,
        monto,
        uuid.UUID(autorizado_por),
        uuid.UUID(creado_por),
    )
    return str(devolucion_id)


async def listar_por_apertura(
    conn: asyncpg.Connection, apertura_caja_id: str
) -> list[dict[str, Any]]:
    rows = await conn.fetch(_LISTAR_POR_APERTURA, uuid.UUID(apertura_caja_id))
    return [dict(r) for r in rows]


_ES_ADMIN_DE_SUCURSAL = """
    SELECT EXISTS (
        SELECT 1
        FROM public.usuarios u
        JOIN public.roles r ON r.id = u.rol
        WHERE u.id = $1
          AND u.activo = TRUE
          AND (
              r.nombre = 'AdministradorSistema'
              OR (
                  r.nombre = 'Administrador'
                  AND EXISTS (
                      SELECT 1 FROM public.usuarios_sucursal us
                      WHERE us.usuario_id = u.id
                        AND us.sucursal_id = $2
                        AND us.activo = TRUE
                  )
              )
          )
    )
"""


async def es_admin_de_sucursal(conn: asyncpg.Connection, usuario_id: str, sucursal_id: str) -> bool:
    """Quien autoriza la cancelación: Administrador activo asignado a la
    sucursal de la comanda, o AdministradorSistema (todas las sucursales)."""
    return bool(
        await conn.fetchval(
            _ES_ADMIN_DE_SUCURSAL, uuid.UUID(str(usuario_id)), uuid.UUID(str(sucursal_id))
        )
    )
