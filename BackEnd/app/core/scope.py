"""Alcance de sucursal derivado del usuario autenticado.

Antes duplicado de forma idéntica en app/services/estancias.py y
app/services/comanda_service.py; centralizado aquí para reutilizarlo en
cualquier endpoint que deba filtrar por sucursal.

Regla única de aislamiento por sucursal.

- Roles con sucursal fija (Administrador, Cajero, Cocina, Atención y
  cualquier rol personalizado): la sucursal es SIEMPRE la de la sesión
  (``branch_id`` del JWT). Un ``sucursal_id`` distinto en query/body/path
  responde 403; sin ``sucursal_id`` se usa la de la sesión, nunca "todas".
- AdministradorSistema: la sucursal del parámetro o, si no hay, la elegida
  en el selector (``X-Sucursal-Vista``, que ``get_current_user`` vuelca en
  ``branch_id``); sin ninguna de las dos, ``VE_TODAS_LAS_SUCURSALES``.
- Recursos por id: si el recurso no es de la sucursal de la sesión se
  responde 404 (no se revela que existe). Ver
  ``app/services/alcance_service.py``.
"""

from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status

from app.core.roles import ROL_SISTEMA
from app.exceptions import NoEncontrado
from app.schemas.auth import TokenData

VE_TODAS_LAS_SUCURSALES = None


def _sin_sucursal_activa() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "SIN_SUCURSAL", "message": "La sesión no tiene una sucursal activa."},
    )


def _otra_sucursal() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "FORBIDDEN_SUCURSAL",
            "message": "No tienes acceso a los datos de otra sucursal.",
        },
    )


def _sucursal_requerida() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": "SUCURSAL_REQUERIDA",
            "message": "Indica la sucursal (sucursal_id o el selector de sucursal).",
        },
    )


def es_sistema(current_user: TokenData) -> bool:
    return current_user.role == ROL_SISTEMA


def sucursal_scope(current_user: TokenData) -> str | None:
    """Sucursal a la que debe limitarse current_user, o VE_TODAS_LAS_SUCURSALES
    (None) si el rol ve todas las sucursales (AdministradorSistema). Si el
    usuario no es AdministradorSistema y no tiene sucursal asignada, devuelve
    un id que no existe para que el filtro no traiga nada, en vez de
    reventar.

    AdministradorSistema puede "pararse" en una sucursal específica (header
    X-Sucursal-Vista, resuelto en get_current_user) -- en ese caso branch_id
    ya viene poblado en el token y se filtra igual que cualquier otro rol."""
    if current_user.role == ROL_SISTEMA and current_user.branch_id is None:
        return VE_TODAS_LAS_SUCURSALES
    if current_user.branch_id is None:
        return "00000000-0000-0000-0000-000000000000"
    return str(current_user.branch_id)


def _a_uuid(valor: UUID | str) -> UUID:
    if isinstance(valor, UUID):
        return valor
    try:
        return UUID(str(valor))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "SUCURSAL_INVALIDA", "message": "El sucursal_id no es válido."},
        ) from None


def resolver_sucursal(current_user: TokenData, solicitada: UUID | str | None) -> UUID | None:
    """Sucursal efectiva para un listado o reporte (regla de aislamiento por sucursal).

    Devuelve None (VE_TODAS_LAS_SUCURSALES) solo para AdministradorSistema
    sin parámetro ni selector. Para el resto de roles nunca devuelve None:
    403 si piden otra sucursal o si la sesión no tiene sucursal."""
    pedida = solicitada if solicitada not in (None, "") else None
    if es_sistema(current_user):
        return _a_uuid(pedida) if pedida is not None else current_user.branch_id
    propia = current_user.branch_id
    if propia is None:
        raise _sin_sucursal_activa()
    if pedida is not None and str(pedida) != str(propia):
        raise _otra_sucursal()
    return propia


def resolver_sucursal_obligatoria(current_user: TokenData, solicitada: UUID | str | None) -> UUID:
    """Igual que resolver_sucursal, pero para endpoints que necesitan una
    sucursal concreta: AdministradorSistema sin parámetro ni selector → 422."""
    sucursal = resolver_sucursal(current_user, solicitada)
    if sucursal is None:
        raise _sucursal_requerida()
    return sucursal


def asegurar_misma_sucursal(
    current_user: TokenData,
    sucursal_recurso: UUID | str | None,
    recurso: str = "Recurso",
    genero: Literal["m", "f"] = "m",
) -> None:
    """404 si el recurso (ya cargado) no es de la sucursal de la sesión.
    AdministradorSistema accede a cualquier sucursal."""
    if es_sistema(current_user):
        return
    if (
        sucursal_recurso is None
        or current_user.branch_id is None
        or str(sucursal_recurso) != str(current_user.branch_id)
    ):
        raise NoEncontrado(recurso, genero)
