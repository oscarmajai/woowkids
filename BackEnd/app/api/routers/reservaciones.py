from datetime import date
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, status

import app.services.disponibilidad as disponibilidad_svc
import app.services.reservaciones as svc
from app.api.deps import apertura_operando_id, require_permission
from app.core.database import get_db
from app.core.scope import resolver_sucursal_obligatoria, sucursal_scope
from app.schemas.auth import TokenData
from app.schemas.disponibilidad import DisponibilidadResponse
from app.schemas.reservaciones import (
    EventoDelDiaOut,
    ReservacionCerrar,
    ReservacionesCrear,
    ReservacionesOut,
    ReservacionesUpdate,
)
from app.schemas.reservaciones_completa import (
    ReservacionCompletaRequest,
    ReservacionCompletaResponse,
)
from app.services import alcance_service

router = APIRouter(prefix="/api/reservaciones", tags=["Reservaciones"])


async def _asegurar_alta(
    conn: asyncpg.Connection,
    current_user: TokenData,
    body: ReservacionesCrear,
    extra_ids: list[UUID] | None = None,
    producto_ids: list[UUID] | None = None,
) -> None:
    """C1: la reservación se crea en la sucursal de la sesión (403 si el body
    trae otra) y su paquete, tipo de evento, extras y productos deben ser de
    esa sucursal (404 si no)."""
    body.sucursal_id = resolver_sucursal_obligatoria(current_user, body.sucursal_id)
    await alcance_service.asegurar_recurso(conn, current_user, "paquete", body.paquete_id)
    await alcance_service.asegurar_recurso(conn, current_user, "tipo_evento", body.tipo_evento_id)
    await alcance_service.asegurar_recursos(conn, current_user, "extra", extra_ids or [])
    await alcance_service.asegurar_recursos(conn, current_user, "producto", producto_ids or [])


@router.get("", response_model=list[ReservacionesOut])
async def listar_reservaciones(
    desde: date | None = Query(None, description="Filtra por fecha_evento >= desde"),
    hasta: date | None = Query(None, description="Filtra por fecha_evento <= hasta"),
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:listar")),
) -> list[ReservacionesOut]:
    return await svc.listar(conn, sucursal_scope(current_user), desde, hasta)


@router.get("/disponibilidad", response_model=DisponibilidadResponse)
async def obtener_disponibilidad(
    fecha: date,
    sucursal_id: UUID | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:ver")),
) -> DisponibilidadResponse:
    sucursal = resolver_sucursal_obligatoria(current_user, sucursal_id)
    return await disponibilidad_svc.obtener_disponibilidad(conn, sucursal, fecha)


@router.get("/evento-cercano/{sucursal_id}", response_model=EventoDelDiaOut | None)
async def obtener_evento_cercano(
    sucursal_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:ver")),
) -> EventoDelDiaOut | None:
    sucursal = resolver_sucursal_obligatoria(current_user, sucursal_id)
    return await svc.obtener_evento_cercano(conn, sucursal)


@router.get("/{reservacion_id}", response_model=ReservacionesOut)
async def obtener_reservacion(
    reservacion_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:ver")),
) -> ReservacionesOut:
    await alcance_service.asegurar_recurso(conn, current_user, "reservacion", reservacion_id)
    return await svc.obtener(conn, reservacion_id)


@router.post("", response_model=ReservacionesOut, status_code=status.HTTP_201_CREATED)
async def crear_reservacion(
    body: ReservacionesCrear,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:crear")),
) -> ReservacionesOut:
    await _asegurar_alta(conn, current_user, body)
    return await svc.crear(conn, body, current_user.sub)


@router.post(
    "/completa",
    response_model=ReservacionCompletaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Alta atómica de una reservación (QA #10)",
    description=(
        "Crea la reservación junto con sus extras, productos y pagos (anticipo) "
        "en una única transacción: si algo falla, nada se persiste. Sustituye "
        "al loop de requests sueltos que hacía NuevaReservacionPage.vue."
    ),
)
async def crear_reservacion_completa(
    body: ReservacionCompletaRequest,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:crear")),
    apertura_id: str = Depends(apertura_operando_id),
) -> ReservacionCompletaResponse:
    from app.services import turnos_caja_service

    await _asegurar_alta(
        conn,
        current_user,
        body.reservacion,
        extra_ids=[e.extra_id for e in body.extras],
        producto_ids=[p.producto_id for p in body.productos],
    )
    disponible_antes = await turnos_caja_service.efectivo_disponible_actual(conn, apertura_id)
    resultado = await svc.crear_completa(conn, body, UUID(current_user.sub), apertura_id)
    if body.pagos:
        resultado.advertencia_efectivo = turnos_caja_service.advertencia_efectivo_insuficiente(
            disponible_antes, body.cambio
        )
    return resultado


@router.patch("/{reservacion_id}", response_model=ReservacionesOut)
async def actualizar_reservacion(
    reservacion_id: UUID,
    body: ReservacionesUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:editar")),
) -> ReservacionesOut:
    await alcance_service.asegurar_recurso(conn, current_user, "reservacion", reservacion_id)
    return await svc.actualizar(conn, reservacion_id, body, UUID(current_user.sub))


@router.post(
    "/{reservacion_id}/cerrar",
    response_model=ReservacionesOut,
    summary="Cierra el evento (pasa la reservación a completada)",
    description=(
        "Solo si el evento ya empezó (hora local de la sucursal), no tiene saldo "
        "pendiente y la reservación no está cancelada ni cerrada; si no, 409. "
        "Las notas del cierre se agregan a las existentes."
    ),
)
async def cerrar_reservacion(
    reservacion_id: UUID,
    body: ReservacionCerrar,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:editar")),
) -> ReservacionesOut:
    await alcance_service.asegurar_recurso(conn, current_user, "reservacion", reservacion_id)
    return await svc.cerrar(conn, reservacion_id, body.notas_cierre, UUID(current_user.sub))


@router.delete("/{reservacion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_reservacion(
    reservacion_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:eliminar")),
) -> None:
    await alcance_service.asegurar_recurso(conn, current_user, "reservacion", reservacion_id)
    await svc.eliminar(conn, reservacion_id)
