"""Aislamiento por sucursal de recursos consultados o modificados por id (C1).

Los routers lo llaman al inicio, antes de delegar al service del recurso:

    await alcance_service.asegurar_recurso(conn, current_user, "insumo", insumo_id)

Para roles con sucursal fija, si el recurso no existe o es de otra sucursal
responde 404 (no se revela que existe). AdministradorSistema no se
restringe. La regla de listados y altas está en ``app/core/scope.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from uuid import UUID

import asyncpg

from app.core.scope import asegurar_misma_sucursal, es_sistema
from app.exceptions import NoEncontrado
from app.repositories import alcance_repository
from app.repositories.alcance_repository import TipoRecurso as TipoRecurso
from app.schemas.auth import TokenData

NOMBRE_RECURSO: dict[str, str] = {
    "insumo": "Insumo",
    "presentacion_insumo": "Presentación",
    "proveedor": "Proveedor",
    "compra": "Compra",
    "paquete": "Paquete",
    "pulsera": "Pulsera",
    "caja": "Caja",
    "apertura_caja": "Turno",
    "reservacion": "Reservación",
    "reservacion_extra": "Extra de reservación",
    "reservacion_producto": "Producto de reservación",
    "pago_reservacion": "Pago",
    "extra": "Extra",
    "tipo_evento": "Tipo de evento",
    "producto": "Producto",
    "comanda": "Comanda",
    "registro": "Registro",
    "detalle_registro": "Registro",
}

# Recursos de género femenino: "Reservación no encontrada" (N15).
RECURSOS_FEMENINOS: frozenset[str] = frozenset(
    {"presentacion_insumo", "compra", "pulsera", "caja", "reservacion", "comanda"}
)


def _a_uuid(recurso_id: UUID | str) -> UUID | None:
    if isinstance(recurso_id, UUID):
        return recurso_id
    try:
        return UUID(str(recurso_id))
    except ValueError:
        return None


async def asegurar_recurso(
    conn: asyncpg.Connection,
    current_user: TokenData,
    tipo: TipoRecurso,
    recurso_id: UUID | str,
) -> None:
    """404 si current_user (rol con sucursal fija) no puede ver el recurso."""
    if es_sistema(current_user):
        return
    nombre = NOMBRE_RECURSO[tipo]
    genero: Literal["m", "f"] = "f" if tipo in RECURSOS_FEMENINOS else "m"
    rid = _a_uuid(recurso_id)
    if rid is None:
        raise NoEncontrado(nombre, genero)
    sucursal = await alcance_repository.sucursal_de(conn, tipo, rid)
    asegurar_misma_sucursal(current_user, sucursal, nombre, genero)


async def asegurar_recursos(
    conn: asyncpg.Connection,
    current_user: TokenData,
    tipo: TipoRecurso,
    recurso_ids: Iterable[UUID | str],
) -> None:
    """asegurar_recurso para una lista (p. ej. productos de un paquete)."""
    unicos: dict[UUID | str, None] = dict.fromkeys(recurso_ids)
    for rid in unicos:
        await asegurar_recurso(conn, current_user, tipo, rid)
