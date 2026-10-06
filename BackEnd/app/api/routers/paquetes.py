from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status

import app.services.paquetes as svc
from app.api.deps import require_permission
from app.core.database import get_db
from app.core.scope import resolver_sucursal, resolver_sucursal_obligatoria
from app.schemas.auth import TokenData
from app.schemas.paquetes import PaquetesCreate, PaquetesOut, PaquetesUpdate
from app.services import alcance_service

router = APIRouter(prefix="/api/paquetes", tags=["Paquetes"])


@router.get("", response_model=list[PaquetesOut])
async def listar_paquetes(
    sucursal_id: UUID | None = None,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("paquetes:listar")),
) -> list[PaquetesOut]:
    return await svc.listar(conn, resolver_sucursal(current_user, sucursal_id))


@router.get("/{paquete_id}", response_model=PaquetesOut)
async def obtener_paquete(
    paquete_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("paquetes:ver")),
) -> PaquetesOut:
    await alcance_service.asegurar_recurso(conn, current_user, "paquete", paquete_id)
    return await svc.obtener(conn, paquete_id)


@router.post("", response_model=PaquetesOut, status_code=status.HTTP_201_CREATED)
async def crear_paquete(
    body: PaquetesCreate,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("paquetes:crear")),
) -> PaquetesOut:
    # El paquete se crea en la sucursal de la sesión (403 si el body
    # trae otra) y sus productos deben ser de esa sucursal (404).
    body.sucursal_id = resolver_sucursal_obligatoria(current_user, body.sucursal_id)
    await alcance_service.asegurar_recursos(
        conn, current_user, "producto", [p.producto_id for p in body.productos_incluidos or []]
    )
    return await svc.crear(conn, body)


@router.patch("/{paquete_id}", response_model=PaquetesOut)
async def actualizar_paquete(
    paquete_id: UUID,
    body: PaquetesUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("paquetes:editar")),
) -> PaquetesOut:
    await alcance_service.asegurar_recurso(conn, current_user, "paquete", paquete_id)
    await alcance_service.asegurar_recursos(
        conn, current_user, "producto", [p.producto_id for p in body.productos_incluidos or []]
    )
    return await svc.actualizar(conn, paquete_id, body)


@router.delete("/{paquete_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_paquete(
    paquete_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("paquetes:eliminar")),
) -> None:
    await alcance_service.asegurar_recurso(conn, current_user, "paquete", paquete_id)
    await svc.eliminar(conn, paquete_id)


@router.post(
    "/{paquete_id}/duplicar", response_model=PaquetesOut, status_code=status.HTTP_201_CREATED
)
async def duplicar_paquete(
    paquete_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("paquetes:crear")),
) -> PaquetesOut:
    await alcance_service.asegurar_recurso(conn, current_user, "paquete", paquete_id)
    return await svc.duplicar(conn, paquete_id, UUID(current_user.sub))
