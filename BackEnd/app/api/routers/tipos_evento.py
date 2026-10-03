from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status

import app.services.tipos_evento as svc
from app.api.deps import require_permission
from app.core.database import get_db
from app.core.scope import resolver_sucursal_obligatoria, sucursal_scope
from app.schemas.auth import TokenData
from app.schemas.tipos_evento import TiposEventoCreate, TiposEventoOut, TiposEventoUpdate
from app.services import alcance_service

router = APIRouter(prefix="/api/tipos-evento", tags=["Tipos de Evento"])


@router.get("", response_model=list[TiposEventoOut])
async def listar_tipos_evento(
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(
        require_permission("tipos_evento:listar", "reservaciones:crear")
    ),
) -> list[TiposEventoOut]:
    scope = sucursal_scope(current_user)
    return await svc.listar(conn, UUID(scope) if scope is not None else None)


@router.get("/{tipo_evento_id}", response_model=TiposEventoOut)
async def obtener_tipo_evento(
    tipo_evento_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("tipos_evento:ver")),
) -> TiposEventoOut:
    await alcance_service.asegurar_recurso(conn, current_user, "tipo_evento", tipo_evento_id)
    return await svc.obtener(conn, tipo_evento_id)


@router.post("", response_model=TiposEventoOut, status_code=status.HTTP_201_CREATED)
async def crear_tipo_evento(
    body: TiposEventoCreate,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("tipos_evento:crear")),
) -> TiposEventoOut:
    # sucursal_id siempre se deriva del usuario autenticado, nunca se confía
    # en lo que mande el cliente -- ya no existe el concepto de tipo de
    # evento "global" (sucursal_id NULL).
    # C1: roles con sucursal fija → la de la sesión (403 si mandan otra);
    # AdministradorSistema → la del body o la del selector (422 sin ninguna).
    body.sucursal_id = resolver_sucursal_obligatoria(current_user, body.sucursal_id)
    return await svc.crear(conn, body)


@router.patch("/{tipo_evento_id}", response_model=TiposEventoOut)
async def actualizar_tipo_evento(
    tipo_evento_id: UUID,
    body: TiposEventoUpdate,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("tipos_evento:editar")),
) -> TiposEventoOut:
    await alcance_service.asegurar_recurso(conn, current_user, "tipo_evento", tipo_evento_id)
    return await svc.actualizar(conn, tipo_evento_id, body)


@router.delete("/{tipo_evento_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_tipo_evento(
    tipo_evento_id: UUID,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("tipos_evento:eliminar")),
) -> None:
    await alcance_service.asegurar_recurso(conn, current_user, "tipo_evento", tipo_evento_id)
    await svc.eliminar(conn, tipo_evento_id)
