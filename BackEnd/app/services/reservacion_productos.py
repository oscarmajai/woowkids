"""Productos adicionales de una reservación ya levantada (N11).

El precio sale del catálogo, nunca del request; cada alta, cambio o baja
recalcula el total de la reservación con las reglas del alta (C2) y respeta la
máquina de estados (A8) y el plazo de edición (N12)."""

from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core.scope import sucursal_scope
from app.exceptions import NoEncontrado
from app.repositories import reservacion_productos_repository, reservaciones_repository
from app.schemas.auth import TokenData
from app.schemas.reservacion_productos import (
    ReservacionProductosCreate,
    ReservacionProductosOut,
    ReservacionProductosUpdate,
)
from app.services import reservaciones as reservaciones_svc


async def listar_por_reservacion(
    conn: asyncpg.Connection, reservacion_id: UUID, current_user: TokenData
) -> list[ReservacionProductosOut]:
    reservacion = await reservaciones_repository.obtener(conn, reservacion_id)
    if not reservacion:
        raise NoEncontrado("Reservación")

    scope = sucursal_scope(current_user)
    if scope is not None and str(reservacion["sucursal_id"]) != scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puede consultar productos de reservaciones de otra sucursal.",
        )

    rows = await reservacion_productos_repository.listar_por_reservacion(conn, reservacion_id)
    return [ReservacionProductosOut.model_validate(r) for r in rows]


async def obtener(
    conn: asyncpg.Connection, reservacion_producto_id: UUID
) -> ReservacionProductosOut:
    row = await reservacion_productos_repository.obtener(conn, reservacion_producto_id)
    if not row:
        raise NoEncontrado("Producto de reservación")
    return ReservacionProductosOut.model_validate(row)


async def crear(
    conn: asyncpg.Connection, body: ReservacionProductosCreate, current_user: TokenData
) -> ReservacionProductosOut:
    usuario_id = UUID(current_user.sub)
    async with conn.transaction():
        reservacion = await reservaciones_svc.bloquear_para_partidas(conn, body.reservacion_id)
        producto = await reservaciones_svc.producto_de_catalogo(
            conn, body.producto_id, reservacion["sucursal_id"]
        )
        row = await reservacion_productos_repository.crear(
            conn,
            reservacion_id=body.reservacion_id,
            producto_id=body.producto_id,
            cantidad=body.cantidad,
            precio_unitario=producto.precio_unitario,
            notas=body.notas,
            creado_por=usuario_id,
        )
        await reservaciones_svc.recalcular_total_por_partidas(
            conn, reservacion, usuario_id, body.precio_total
        )
    return ReservacionProductosOut.model_validate(row)


async def actualizar(
    conn: asyncpg.Connection,
    reservacion_producto_id: UUID,
    body: ReservacionProductosUpdate,
    usuario_id: UUID,
) -> ReservacionProductosOut:
    """Cambia cantidad o notas y vuelve a tomar el precio del catálogo."""
    actual = await obtener(conn, reservacion_producto_id)
    async with conn.transaction():
        reservacion = await reservaciones_svc.bloquear_para_partidas(conn, actual.reservacion_id)
        producto = await reservaciones_svc.producto_de_catalogo(
            conn, actual.producto_id, reservacion["sucursal_id"]
        )
        updates = body.model_dump(include={"cantidad", "notas"}, exclude_unset=True)
        if updates.get("cantidad") is None:
            updates.pop("cantidad", None)
        updates["precio_unitario"] = producto.precio_unitario
        row = await reservacion_productos_repository.actualizar(
            conn, reservacion_producto_id, updates
        )
        if not row:
            raise NoEncontrado("Producto de reservación")
        await reservaciones_svc.recalcular_total_por_partidas(
            conn, reservacion, usuario_id, body.precio_total
        )
    return ReservacionProductosOut.model_validate(row)


async def eliminar(
    conn: asyncpg.Connection, reservacion_producto_id: UUID, usuario_id: UUID
) -> None:
    actual = await obtener(conn, reservacion_producto_id)
    async with conn.transaction():
        reservacion = await reservaciones_svc.bloquear_para_partidas(conn, actual.reservacion_id)
        await reservacion_productos_repository.eliminar(conn, reservacion_producto_id)
        await reservaciones_svc.recalcular_total_por_partidas(conn, reservacion, usuario_id)
