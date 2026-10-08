from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status

import app.services.reservacion_productos as svc
from app.api.deps import require_permission
from app.core.database import get_db
from app.schemas.auth import TokenData
from app.schemas.reservacion_productos import (
    ReservacionProductosCreate,
    ReservacionProductosOut,
    ReservacionProductosUpdate,
)
from app.services import alcance_service

router = APIRouter(prefix="/api/reservacion-productos", tags=["Reservación Productos"])


@router.get("/reservacion/{reservacion_id}", response_model=list[ReservacionProductosOut])
async def listar_por_reservacion(
    reservacion_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:gestionar_productos")),
) -> list[ReservacionProductosOut]:
    await alcance_service.asegurar_recurso(conn, current_user, "reservacion", reservacion_id)
    return await svc.listar_por_reservacion(conn, reservacion_id, current_user)


@router.get("/{reservacion_producto_id}", response_model=ReservacionProductosOut)
async def obtener_reservacion_producto(
    reservacion_producto_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:gestionar_productos")),
) -> ReservacionProductosOut:
    await alcance_service.asegurar_recurso(
        conn, current_user, "reservacion_producto", reservacion_producto_id
    )
    return await svc.obtener(conn, reservacion_producto_id)


@router.post("", response_model=ReservacionProductosOut, status_code=status.HTTP_201_CREATED)
async def crear_reservacion_producto(
    body: ReservacionProductosCreate,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:gestionar_productos")),
) -> ReservacionProductosOut:
    # La reservación y el producto deben ser de la sucursal de la sesión.
    await alcance_service.asegurar_recurso(conn, current_user, "reservacion", body.reservacion_id)
    await alcance_service.asegurar_recurso(conn, current_user, "producto", body.producto_id)
    return await svc.crear(conn, body, current_user)


@router.patch("/{reservacion_producto_id}", response_model=ReservacionProductosOut)
async def actualizar_reservacion_producto(
    reservacion_producto_id: UUID,
    body: ReservacionProductosUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:gestionar_productos")),
) -> ReservacionProductosOut:
    await alcance_service.asegurar_recurso(
        conn, current_user, "reservacion_producto", reservacion_producto_id
    )
    return await svc.actualizar(conn, reservacion_producto_id, body, UUID(current_user.sub))


@router.delete("/{reservacion_producto_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_reservacion_producto(
    reservacion_producto_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("reservaciones:gestionar_productos")),
) -> None:
    await alcance_service.asegurar_recurso(
        conn, current_user, "reservacion_producto", reservacion_producto_id
    )
    await svc.eliminar(conn, reservacion_producto_id, UUID(current_user.sub))
