"""Aviso de privacidad (/api/privacidad). La consulta del aviso vigente es
pública (sin sesión): la usan la página /aviso-de-privacidad, el registro de
entrada y el portal de padres. Editar y publicar es del AdministradorSistema."""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, status

from app.api.deps import require_role
from app.core.database import get_db
from app.core.roles import ROL_SISTEMA
from app.schemas.auth import TokenData
from app.schemas.privacidad import AvisoAdminOut, AvisoPublicoOut, PublicarAvisoIn
from app.services import privacidad_service

router = APIRouter(prefix="/api/privacidad", tags=["Privacidad"])


@router.get(
    "/aviso",
    response_model=AvisoPublicoOut,
    summary="Aviso de privacidad vigente (público)",
)
async def aviso_vigente(conn: asyncpg.Connection = Depends(get_db)) -> AvisoPublicoOut:
    return await privacidad_service.aviso_publico(conn)


@router.get(
    "/admin/aviso",
    response_model=AvisoAdminOut,
    summary="Aviso vigente como plantilla, datos del responsable e historial",
)
async def aviso_admin(
    current_user: TokenData = Depends(require_role(ROL_SISTEMA)),
    conn: asyncpg.Connection = Depends(get_db),
) -> AvisoAdminOut:
    return await privacidad_service.aviso_admin(conn)


@router.post(
    "/admin/aviso",
    response_model=AvisoAdminOut,
    status_code=status.HTTP_201_CREATED,
    summary="Publicar una versión nueva del aviso de privacidad",
)
async def publicar_aviso(
    body: PublicarAvisoIn,
    current_user: TokenData = Depends(require_role(ROL_SISTEMA)),
    conn: asyncpg.Connection = Depends(get_db),
) -> AvisoAdminOut:
    return await privacidad_service.publicar(conn, body, UUID(current_user.sub))
