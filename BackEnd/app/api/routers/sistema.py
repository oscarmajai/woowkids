"""Estado del sistema para el AdministradorSistema (/api/sistema)."""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends

from app.api.deps import require_role
from app.core.database import get_db
from app.core.roles import ROL_SISTEMA
from app.schemas.auth import TokenData
from app.schemas.respaldos import EstadoRespaldosOut
from app.services import respaldos_service

router = APIRouter(prefix="/api/sistema", tags=["Sistema"])


@router.get(
    "/respaldos",
    response_model=EstadoRespaldosOut,
    summary="Último respaldo automático y si hay que avisar de una falla",
)
async def estado_respaldos(
    current_user: TokenData = Depends(require_role(ROL_SISTEMA)),
    conn: asyncpg.Connection = Depends(get_db),
) -> EstadoRespaldosOut:
    return await respaldos_service.estado(conn)
