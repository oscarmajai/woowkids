"""
app/api/routers/horarios.py
CRUD administrativo de horarios/turnos de trabajo (/api/horarios).
Las reglas de alcance por sucursal (M19) viven en app/services/horarios_service.py.
"""

from __future__ import annotations

from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, Query, status

from app.api.deps import require_permission
from app.core.database import get_db
from app.schemas.auth import TokenData
from app.schemas.horarios_cajas import HorarioCreate, HorarioResponse, HorarioUpdate
from app.services import horarios_service

router = APIRouter(prefix="/api/horarios", tags=["Horarios"])


@router.get(
    "",
    response_model=list[HorarioResponse],
    summary="Lista los horarios de la sucursal más los globales",
)
async def listar(
    sucursal_id: UUID | None = Query(None),
    current_user: TokenData = Depends(require_permission("horarios:listar")),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[HorarioResponse]:
    return await horarios_service.listar(conn, current_user, sucursal_id)


@router.post(
    "",
    response_model=HorarioResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea un horario en la sucursal de la sesión (global si es AdministradorSistema)",
)
async def crear(
    payload: HorarioCreate,
    current_user: TokenData = Depends(require_permission("horarios:crear")),
    conn: asyncpg.Connection = Depends(get_db),
) -> HorarioResponse:
    return await horarios_service.crear(conn, current_user, payload)


@router.patch(
    "/{horario_id}",
    response_model=HorarioResponse,
    summary="Edita un horario de trabajo existente",
)
async def editar(
    horario_id: str,
    payload: HorarioUpdate,
    current_user: TokenData = Depends(require_permission("horarios:editar")),
    conn: asyncpg.Connection = Depends(get_db),
) -> HorarioResponse:
    return await horarios_service.editar(conn, current_user, horario_id, payload)


@router.delete(
    "/{horario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Desactiva un horario de trabajo (borrado lógico)",
)
async def eliminar(
    horario_id: str,
    current_user: TokenData = Depends(require_permission("horarios:eliminar")),
    conn: asyncpg.Connection = Depends(get_db),
) -> None:
    await horarios_service.eliminar(conn, current_user, horario_id)
