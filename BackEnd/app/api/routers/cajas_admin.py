"""
app/api/routers/cajas_admin.py
CRUD administrativo de cajas físicas (/api/cajas).
Filtrado automático por la sucursal del usuario autenticado.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.roles import ROL_SISTEMA
from app.repositories.caja_repository import (
    actualizar_caja_admin,
    bloquear_caja,
    caja_tiene_turno_activo,
    crear_caja_admin,
    eliminar_caja_admin,
    get_caja_admin_por_id,
    listar_cajas_admin,
)
from app.schemas.auth import TokenData
from app.schemas.horarios_cajas import CajaAdminCreate, CajaAdminResponse, CajaAdminUpdate

router = APIRouter(prefix="/api/cajas", tags=["Cajas (Admin)"])

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={"code": "CAJA_NOT_FOUND", "message": "Caja no encontrada."},
)

_SIN_SUCURSAL = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail={"code": "SIN_SUCURSAL", "message": "El usuario no tiene sucursal asignada."},
)

_FORBIDDEN_SUCURSAL = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail={
        "code": "FORBIDDEN",
        "message": "No puedes consultar las cajas de otra sucursal.",
    },
)

_NUMERO_DUPLICADO = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={
        "code": "NUMERO_DUPLICADO",
        "message": "Ya existe una caja activa con ese número en esta sucursal.",
    },
)


_CAJA_CON_TURNO = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={
        "code": "CAJA_CON_TURNO_ABIERTO",
        "message": (
            "La caja tiene un turno abierto. Pide al cajero que haga el cierre antes de "
            "desactivarla."
        ),
    },
)


async def _asegurar_sin_turno_activo(conn: asyncpg.Connection, caja_id: str) -> None:
    """Una caja con turno ABIERTA o EN_CORTE no se desactiva (dejaría al
    cajero operando una caja que ya no existe para el resto del sistema).
    Debe correr dentro de una transacción: bloquea la caja para que una
    apertura en curso termine antes de revisar."""
    await bloquear_caja(conn, caja_id)
    if await caja_tiene_turno_activo(conn, caja_id):
        raise _CAJA_CON_TURNO


def _branch_id(current_user: TokenData) -> str:
    if not current_user.branch_id:
        raise _SIN_SUCURSAL
    return str(current_user.branch_id)


def _asegurar_caja_editable(current_user: TokenData, caja: dict[str, Any] | None) -> None:
    """404 si la caja no existe o no es de la sucursal de la sesión.

    El AdministradorSistema edita cualquier caja con la sucursal de la
    propia caja (antes exigía una sucursal en la sesión: 400 SIN_SUCURSAL en la
    vista "Todas las sucursales")."""
    if caja is None:
        raise _NOT_FOUND
    if current_user.role == ROL_SISTEMA:
        return
    if caja["sucursal_id"] != _branch_id(current_user):
        raise _NOT_FOUND


def _resolver_sucursal(current_user: TokenData, sucursal_id: UUID | None) -> str | None:
    """AdministradorSistema puede consultar cualquier sucursal vía el
    parámetro opcional; el resto solo la suya (403 si pide otra). Sin el
    parámetro, la sucursal de la sesión; el AdministradorSistema sin
    sucursal elegida ve las de todas (None)."""
    if sucursal_id is None:
        if current_user.role == ROL_SISTEMA and current_user.branch_id is None:
            return None
        return _branch_id(current_user)
    if current_user.role == ROL_SISTEMA:
        return str(sucursal_id)
    if str(current_user.branch_id) != str(sucursal_id):
        raise _FORBIDDEN_SUCURSAL
    return str(sucursal_id)


@router.get("", response_model=list[CajaAdminResponse], summary="Lista las cajas de la sucursal")
async def listar(
    sucursal_id: UUID | None = Query(None),
    current_user: TokenData = Depends(require_permission("cajas:listar")),
    conn: asyncpg.Connection = Depends(get_db),
) -> list[CajaAdminResponse]:
    rows = await listar_cajas_admin(conn, sucursal_id=_resolver_sucursal(current_user, sucursal_id))
    return [CajaAdminResponse(**r) for r in rows]


@router.post(
    "",
    response_model=CajaAdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crea una nueva caja en la sucursal del usuario",
)
async def crear(
    payload: CajaAdminCreate,
    current_user: TokenData = Depends(require_permission("cajas:crear")),
    conn: asyncpg.Connection = Depends(get_db),
) -> CajaAdminResponse:
    try:
        row = await crear_caja_admin(
            conn,
            sucursal_id=_branch_id(current_user),
            nombre=payload.nombre,
            numero=payload.numero,
            creado_por=current_user.sub,
            impresora=payload.impresora,
        )
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise _NUMERO_DUPLICADO from exc
        raise
    return CajaAdminResponse(**row)


@router.patch(
    "/{caja_id}",
    response_model=CajaAdminResponse,
    summary="Edita una caja de la sucursal",
)
async def editar(
    caja_id: str,
    payload: CajaAdminUpdate,
    current_user: TokenData = Depends(require_permission("cajas:editar")),
    conn: asyncpg.Connection = Depends(get_db),
) -> CajaAdminResponse:
    existing = await get_caja_admin_por_id(conn, caja_id)
    _asegurar_caja_editable(current_user, existing)
    assert existing is not None

    try:
        async with conn.transaction():
            if payload.activo is False and existing["activo"]:
                await _asegurar_sin_turno_activo(conn, caja_id)
            row = await actualizar_caja_admin(
                conn,
                caja_id=caja_id,
                nombre=payload.nombre,
                numero=payload.numero,
                activo=payload.activo,
                modificado_por=current_user.sub,
                impresora=payload.impresora,
                actualizar_impresora="impresora" in payload.model_fields_set,
            )
    except HTTPException:
        raise
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise _NUMERO_DUPLICADO from exc
        raise
    if row is None:
        raise _NOT_FOUND
    return CajaAdminResponse(**row)


@router.delete(
    "/{caja_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Desactiva una caja de la sucursal (borrado lógico)",
)
async def eliminar(
    caja_id: str,
    current_user: TokenData = Depends(require_permission("cajas:eliminar")),
    conn: asyncpg.Connection = Depends(get_db),
) -> None:
    _asegurar_caja_editable(current_user, await get_caja_admin_por_id(conn, caja_id))

    async with conn.transaction():
        await _asegurar_sin_turno_activo(conn, caja_id)
        await eliminar_caja_admin(conn, caja_id=caja_id, modificado_por=current_user.sub)
