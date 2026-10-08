"""Extras de una reservación ya levantada.

El precio sale del catálogo y la cantidad de la unidad del extra, nunca
del request; cada alta, cambio o baja recalcula el total de la reservación con
las reglas del alta y respeta la máquina de estados y el plazo de
edición."""

from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core.scope import sucursal_scope
from app.exceptions import NoEncontrado
from app.repositories import reservacion_extras_repository, reservaciones_repository
from app.schemas.auth import TokenData
from app.schemas.reservacion_extras import (
    ReservacionExtrasCreate,
    ReservacionExtrasOut,
    ReservacionExtrasUpdate,
)
from app.services import reservacion_precio
from app.services import reservaciones as reservaciones_svc


async def listar_por_reservacion(
    conn: asyncpg.Connection, reservacion_id: UUID, current_user: TokenData
) -> list[ReservacionExtrasOut]:
    reservacion = await reservaciones_repository.obtener(conn, reservacion_id)
    if not reservacion:
        raise NoEncontrado("Reservación", genero="f")

    scope = sucursal_scope(current_user)
    if scope is not None and str(reservacion["sucursal_id"]) != scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No puede consultar extras de reservaciones de otra sucursal.",
        )

    rows = await reservacion_extras_repository.listar_por_reservacion(conn, reservacion_id)
    return [ReservacionExtrasOut.model_validate(r) for r in rows]


async def obtener(conn: asyncpg.Connection, reservacion_extra_id: UUID) -> ReservacionExtrasOut:
    row = await reservacion_extras_repository.obtener(conn, reservacion_extra_id)
    if not row:
        raise NoEncontrado("Extra de reservación")
    return ReservacionExtrasOut.model_validate(row)


def _horas(reservacion: dict[str, Any]) -> int:
    """Horas del evento: las guardadas o, en reservaciones viejas sin ellas,
    las facturables del horario."""
    return int(reservacion["horas_reservadas"]) or reservacion_precio.horas_facturables(
        reservacion["hora_inicio"], reservacion["hora_fin"]
    )


async def _cotizar(
    conn: asyncpg.Connection, reservacion: dict[str, Any], extra_id: UUID
) -> dict[str, Any]:
    """Precio de catálogo y cantidad por unidad del extra para esta reservación."""
    extra = await reservaciones_svc.extra_de_catalogo(conn, extra_id, reservacion["sucursal_id"])
    return {
        "precio_unitario": extra["precio"],
        "cantidad": reservacion_precio.cantidad_extra(
            extra.get("unidad"), int(reservacion["numero_personas"]), _horas(reservacion)
        ),
    }


async def crear(
    conn: asyncpg.Connection, body: ReservacionExtrasCreate, usuario_id: UUID
) -> ReservacionExtrasOut:
    async with conn.transaction():
        reservacion = await reservaciones_svc.bloquear_para_partidas(conn, body.reservacion_id)
        cotizacion = await _cotizar(conn, reservacion, body.extra_id)
        row = await reservacion_extras_repository.crear(
            conn,
            reservacion_id=body.reservacion_id,
            extra_id=body.extra_id,
            creado_por=usuario_id,
            **cotizacion,
        )
        await reservaciones_svc.recalcular_total_por_partidas(
            conn, reservacion, usuario_id, body.precio_total
        )
    return ReservacionExtrasOut.model_validate(row)


async def actualizar(
    conn: asyncpg.Connection,
    reservacion_extra_id: UUID,
    body: ReservacionExtrasUpdate,
    usuario_id: UUID,
) -> ReservacionExtrasOut:
    """Actualiza el extra al precio vigente del catálogo y a la cantidad que
    toca por su unidad; lo que traiga el request en esos campos se ignora."""
    actual = await obtener(conn, reservacion_extra_id)
    async with conn.transaction():
        reservacion = await reservaciones_svc.bloquear_para_partidas(conn, actual.reservacion_id)
        cotizacion = await _cotizar(conn, reservacion, actual.extra_id)
        row = await reservacion_extras_repository.actualizar(conn, reservacion_extra_id, cotizacion)
        if not row:
            raise NoEncontrado("Extra de reservación")
        await reservaciones_svc.recalcular_total_por_partidas(
            conn, reservacion, usuario_id, body.precio_total
        )
    return ReservacionExtrasOut.model_validate(row)


async def eliminar(conn: asyncpg.Connection, reservacion_extra_id: UUID, usuario_id: UUID) -> None:
    actual = await obtener(conn, reservacion_extra_id)
    async with conn.transaction():
        reservacion = await reservaciones_svc.bloquear_para_partidas(conn, actual.reservacion_id)
        await reservacion_extras_repository.eliminar(conn, reservacion_extra_id)
        await reservaciones_svc.recalcular_total_por_partidas(conn, reservacion, usuario_id)
