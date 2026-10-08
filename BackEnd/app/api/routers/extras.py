from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status

import app.services.extras as svc
from app.api.deps import require_permission
from app.core.database import get_db
from app.core.scope import resolver_sucursal_obligatoria, sucursal_scope
from app.schemas.auth import TokenData
from app.schemas.extras import ExtrasCrear, ExtrasOut, ExtrasUpdate
from app.services import alcance_service

router = APIRouter(prefix="/api/extras", tags=["Extras"])


@router.get("", response_model=list[ExtrasOut])
async def listar_extras(
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("extras:listar")),
) -> list[ExtrasOut]:
    scope = sucursal_scope(current_user)
    return await svc.listar(conn, UUID(scope) if scope is not None else None)


@router.get("/{extra_id}", response_model=ExtrasOut)
async def obtener_extra(
    extra_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("extras:ver")),
) -> ExtrasOut:
    await alcance_service.asegurar_recurso(conn, current_user, "extra", extra_id)
    return await svc.obtener(conn, extra_id)


@router.post("", response_model=ExtrasOut, status_code=status.HTTP_201_CREATED)
async def crear_extra(
    body: ExtrasCrear,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("extras:crear")),
) -> ExtrasOut:
    # sucursal_id siempre se deriva del usuario autenticado, nunca se confía
    # en lo que mande el cliente -- ya no existe el concepto de extra
    # "global" (sucursal_id NULL).
    # Roles con sucursal fija → la de la sesión (403 si mandan otra);
    # AdministradorSistema → la del body o la del selector (422 sin ninguna).
    body.sucursal_id = resolver_sucursal_obligatoria(current_user, body.sucursal_id)
    return await svc.crear(conn, body)


@router.patch("/{extra_id}", response_model=ExtrasOut)
async def actualizar_extra(
    extra_id: UUID,
    body: ExtrasUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("extras:editar")),
) -> ExtrasOut:
    await alcance_service.asegurar_recurso(conn, current_user, "extra", extra_id)
    return await svc.actualizar(conn, extra_id, body)


@router.delete("/{extra_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_extra(
    extra_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("extras:eliminar")),
) -> None:
    await alcance_service.asegurar_recurso(conn, current_user, "extra", extra_id)
    await svc.eliminar(conn, extra_id)
