"""
app/services/horarios_service.py
Reglas de alcance de los horarios de trabajo (tabla turnos).

- Horario global (``sucursal_id`` NULL): lo ven todas las sucursales y solo
  el AdministradorSistema lo crea, edita o desactiva (así quedaron los que ya
  existían).
- Horario de sucursal: se crea en la sucursal de quien lo crea y solo esa
  sucursal lo ve y lo edita. El AdministradorSistema puede tocar cualquiera.
- Listados (y la apertura de caja): los de la sucursal más los globales; el
  AdministradorSistema sin selector de sucursal ve todos.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import asyncpg
from fastapi import HTTPException, status

from app.core.scope import es_sistema, resolver_sucursal
from app.repositories import horarios_repository
from app.schemas.auth import TokenData
from app.schemas.horarios_cajas import HorarioCreate, HorarioResponse, HorarioUpdate

_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail={"code": "HORARIO_NOT_FOUND", "message": "Horario no encontrado."},
)

_NOMBRE_DUPLICADO = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail={"code": "NOMBRE_DUPLICADO", "message": "Ya existe un horario con ese nombre."},
)

_SOLO_SISTEMA = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN,
    detail={
        "code": "HORARIO_GLOBAL",
        "message": (
            "Este horario es compartido por todas las sucursales; solo el "
            "Administrador del Sistema puede editarlo o desactivarlo."
        ),
    },
)


async def listar(
    conn: asyncpg.Connection, current_user: TokenData, sucursal_id: UUID | None
) -> list[HorarioResponse]:
    sucursal = resolver_sucursal(current_user, sucursal_id)
    rows = await horarios_repository.listar_horarios(conn, sucursal)
    return [HorarioResponse(**r) for r in rows]


async def crear(
    conn: asyncpg.Connection, current_user: TokenData, payload: HorarioCreate
) -> HorarioResponse:
    # Roles con sucursal fija: la suya (403 si piden otra). AdministradorSistema:
    # la indicada o la del selector; sin ninguna, el horario es global.
    sucursal = resolver_sucursal(current_user, payload.sucursal_id)
    if await horarios_repository.existe_nombre(conn, payload.nombre, sucursal):
        raise _NOMBRE_DUPLICADO
    try:
        row = await horarios_repository.crear_horario(
            conn,
            nombre=payload.nombre,
            hora_inicio=payload.hora_inicio,
            hora_fin=payload.hora_fin,
            creado_por=current_user.sub,
            dias=payload.dias,
            sucursal_id=sucursal,
        )
    except asyncpg.UniqueViolationError as exc:
        raise _NOMBRE_DUPLICADO from exc
    return HorarioResponse(**row)


async def _cargar_editable(
    conn: asyncpg.Connection, current_user: TokenData, horario_id: str
) -> dict[str, Any]:
    """El horario, si current_user puede modificarlo: 404 si no existe o es
    de otra sucursal (no se revela), 403 si es global y no es
    AdministradorSistema."""
    try:
        UUID(horario_id)
    except ValueError:
        raise _NOT_FOUND from None
    horario = await horarios_repository.get_horario_por_id(conn, horario_id)
    if horario is None:
        raise _NOT_FOUND
    if es_sistema(current_user):
        return horario
    if horario["sucursal_id"] is None:
        raise _SOLO_SISTEMA
    if current_user.branch_id is None or horario["sucursal_id"] != str(current_user.branch_id):
        raise _NOT_FOUND
    return horario


async def editar(
    conn: asyncpg.Connection,
    current_user: TokenData,
    horario_id: str,
    payload: HorarioUpdate,
) -> HorarioResponse:
    horario = await _cargar_editable(conn, current_user, horario_id)
    if payload.nombre is not None and payload.nombre != horario["nombre"]:
        sucursal = horario["sucursal_id"]
        if await horarios_repository.existe_nombre(
            conn,
            payload.nombre,
            UUID(str(sucursal)) if sucursal else None,
            excluir_id=horario_id,
        ):
            raise _NOMBRE_DUPLICADO
    try:
        row = await horarios_repository.actualizar_horario(
            conn,
            horario_id=horario_id,
            nombre=payload.nombre,
            hora_inicio=payload.hora_inicio,
            hora_fin=payload.hora_fin,
            activo=payload.activo,
            modificado_por=current_user.sub,
            dias=payload.dias,
            actualizar_dias="dias" in payload.model_fields_set,
        )
    except asyncpg.UniqueViolationError as exc:
        raise _NOMBRE_DUPLICADO from exc
    if row is None:
        raise _NOT_FOUND
    return HorarioResponse(**row)


async def eliminar(conn: asyncpg.Connection, current_user: TokenData, horario_id: str) -> None:
    await _cargar_editable(conn, current_user, horario_id)
    found = await horarios_repository.eliminar_horario(
        conn, horario_id=horario_id, modificado_por=current_user.sub
    )
    if not found:
        raise _NOT_FOUND
