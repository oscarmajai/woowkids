"""Consulta la sucursal dueña de un recurso, para validar el aislamiento por
sucursal (C1) antes de leerlo o modificarlo por id.

Una sola consulta por tipo de recurso; los sub-recursos (extras de una
reservación, presentaciones de un insumo, etc.) heredan la sucursal de su
padre por JOIN."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

import asyncpg

TipoRecurso = Literal[
    "insumo",
    "presentacion_insumo",
    "proveedor",
    "compra",
    "paquete",
    "pulsera",
    "caja",
    "apertura_caja",
    "reservacion",
    "reservacion_extra",
    "reservacion_producto",
    "pago_reservacion",
    "extra",
    "tipo_evento",
    "producto",
    "comanda",
    "registro",
    "detalle_registro",
]

_SQL: dict[str, str] = {
    "insumo": "SELECT sucursal_id FROM public.insumos WHERE id = $1",
    "presentacion_insumo": """
        SELECT i.sucursal_id
        FROM public.presentaciones_insumo p
        JOIN public.insumos i ON i.id = p.insumo_id
        WHERE p.id = $1
    """,
    "proveedor": "SELECT sucursal_id FROM public.proveedores WHERE id = $1",
    "compra": "SELECT sucursal_id FROM public.compras WHERE id = $1",
    "paquete": "SELECT sucursal_id FROM public.paquetes WHERE id = $1",
    "pulsera": "SELECT sucursal_id FROM public.pulseras WHERE id = $1",
    "caja": "SELECT sucursal_id FROM public.cajas WHERE id = $1",
    "apertura_caja": """
        SELECT c.sucursal_id
        FROM public.apertura_caja a
        JOIN public.cajas c ON c.id = a.caja_id
        WHERE a.id = $1
    """,
    "reservacion": "SELECT sucursal_id FROM public.reservaciones WHERE id = $1",
    "reservacion_extra": """
        SELECT r.sucursal_id
        FROM public.reservacion_extras re
        JOIN public.reservaciones r ON r.id = re.reservacion_id
        WHERE re.id = $1
    """,
    "reservacion_producto": """
        SELECT r.sucursal_id
        FROM public.reservacion_productos rp
        JOIN public.reservaciones r ON r.id = rp.reservacion_id
        WHERE rp.id = $1
    """,
    "pago_reservacion": """
        SELECT r.sucursal_id
        FROM public.pagos_reservacion p
        JOIN public.reservaciones r ON r.id = p.reservacion_id
        WHERE p.id = $1
    """,
    "extra": "SELECT sucursal_id FROM public.extras WHERE id = $1",
    "tipo_evento": "SELECT sucursal_id FROM public.tipos_evento WHERE id = $1",
    "producto": "SELECT sucursal_id FROM public.productos WHERE id = $1",
    "comanda": "SELECT sucursal_id FROM public.comandas WHERE id = $1",
    "registro": "SELECT sucursal_id FROM public.registros WHERE id = $1",
    "detalle_registro": "SELECT sucursal_id FROM public.detalles_registro WHERE id = $1",
}


async def sucursal_de(conn: asyncpg.Connection, tipo: TipoRecurso, recurso_id: UUID) -> UUID | None:
    """sucursal_id del recurso, o None si no existe."""
    valor = await conn.fetchval(_SQL[tipo], recurso_id)
    if valor is None:
        return None
    return valor if isinstance(valor, UUID) else UUID(str(valor))
