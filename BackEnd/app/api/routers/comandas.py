"""
app/api/routers/comandas.py
Router de comandas — solo valida entrada y delega al service.
SAD §3.2 / Regla 11.4: el router nunca accede a un repository ni escribe SQL.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from app.api.deps import (
    apertura_operando_id,
    require_permission,
    require_role,
    resolve_ws_auth,
)
from app.core.database import conexion_breve, get_db
from app.core.scope import sucursal_scope
from app.core.ws_manager import CANAL_GLOBAL, manager
from app.schemas.auth import TokenData
from app.schemas.comanda import (
    CambioEstadoRequest,
    ComandaCreate,
    ComandaModifyRequest,
    DevolucionEntregadaRequest,
)
from app.services import alcance_service, comanda_service
from app.services.permission_service import has_permission

logger = logging.getLogger("mercury.ws")

router = APIRouter(prefix="/api/comandas", tags=["Comandas"])


def get_active_branch(current_user: TokenData) -> UUID:
    if current_user.branch_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La sesión no tiene una sucursal activa.",
        )
    return current_user.branch_id


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
async def crear_comanda(
    comanda_in: ComandaCreate,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("restaurante:crear_pedido")),
    _apertura_id: str = Depends(apertura_operando_id),
) -> Any:
    """Crea una comanda nueva con sus detalles, sin cobrarla. Sigue exigiendo
    un turno de caja operando, pero no registra movimiento en la caja:
    lo cobrado entra con su método de pago en POST /pagos/completar."""
    # Obtenemos la sucursal de forma centralizada y segura: nunca confiar en
    # el sucursal_id que mande el cliente en el body.
    active_branch_id = get_active_branch(current_user)
    comanda_in = comanda_in.model_copy(update={"sucursal_id": active_branch_id})
    # Productos de otra sucursal: los rechaza precios_venta (422 PRODUCTO_INVALIDO,
    # igual que uno inexistente) al calcular el cobro con el catálogo de la sesión.

    try:
        comanda = await comanda_service.crear_comanda_pos(conn, comanda_in, current_user)
        return asdict(comanda)
    except HTTPException:
        # Preserva el status code y el {code, message} estructurado de
        # excepciones como StockInsuficienteError — no las aplana a 400 str().
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("")
async def listar_comandas(
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("restaurante:ver_pedidos")),
) -> Any:
    """Lista las comandas activas (P, E, L) de la sucursal del usuario, o de
    todas las sucursales si es AdministradorSistema."""
    comandas = await comanda_service.listar_pendientes(conn, current_user)
    return [asdict(c) for c in comandas]


@router.patch("/{comanda_id}/estado")
async def cambiar_estado(
    comanda_id: str,
    data: CambioEstadoRequest,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(
        require_role("AdministradorSistema", "Administrador", "Cajero", "Cocina")
    ),
) -> Any:
    """Avanza el estado de una comanda (P → E → L → T) o la cancela (C) desde
    P/E/L, con auditoría. Transición inválida o comanda ya cancelada: 409.
    Cancelar una comanda cobrada exige `token_pin_admin` (403
    AUTORIZACION_ADMIN_REQUERIDA, con el turno_id para /turnos-caja/validar-pin-admin)
    y registra la devolución en el turno abierto de quien cancela."""
    await alcance_service.asegurar_recurso(conn, current_user, "comanda", comanda_id)
    try:
        comanda = await comanda_service.cambiar_estado(
            conn,
            comanda_id,
            data.estado_actual.value,
            current_user,
            motivo_cancelacion=data.motivo_cancelacion,
            token_pin_admin=data.token_pin_admin,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if comanda is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comanda no encontrada",
        )

    # El service ya notificó por WebSocket; aquí no se vuelve a emitir.
    return asdict(comanda)


@router.post("/{comanda_id}/devolucion")
async def devolver_entregada(
    comanda_id: str,
    data: DevolucionEntregadaRequest,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("restaurante:registrar_pago")),
) -> Any:
    """Devuelve al cliente el dinero de una comanda ya entregada (T), sin
    regresar su stock. Exige motivo y `token_pin_admin` (403
    AUTORIZACION_ADMIN_REQUERIDA con el turno_id para
    /turnos-caja/validar-pin-admin, como la cancelación de una cobrada).
    Registra la devolución por método en el turno abierto de quien devuelve y
    deja la comanda cancelada. 409 DEVOLUCION_NO_APLICA si no está entregada
    o ya se canceló/devolvió; 409 COMANDA_SIN_PAGOS si no tiene cobros."""
    await alcance_service.asegurar_recurso(conn, current_user, "comanda", comanda_id)
    try:
        comanda = await comanda_service.devolver_entregada(
            conn,
            comanda_id,
            current_user,
            data.motivo,
            token_pin_admin=data.token_pin_admin,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if comanda is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Comanda no encontrada",
        )
    return asdict(comanda)


@router.patch("/{comanda_id}/detalles")
async def modificar_detalles(
    comanda_id: str,
    data: ComandaModifyRequest,
    conn: asyncpg.Connection = Depends(get_db),
    current_user: TokenData = Depends(require_permission("restaurante:registrar_pago")),
) -> Any:
    """Elimina productos de una comanda en estado Pendiente y recalcula el total.

    Si se eliminan todos los productos, cancela automáticamente la comanda
    y requiere motivo_cancelacion en el body. Con `modificado_esperado`,
    409 COMANDA_MODIFICADA si la orden cambió desde que se leyó.
    """
    await alcance_service.asegurar_recurso(conn, current_user, "comanda", comanda_id)
    usuario_id = str(UUID(current_user.sub))
    try:
        comanda = await comanda_service.modificar_comanda_parcial(
            conn,
            comanda_id,
            data.detalles_ids_a_eliminar,
            usuario_id,
            data.motivo_cancelacion,
            modificado_esperado=data.modificado_esperado,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    if comanda is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La comanda no existe o no está en estado Pendiente.",
        )

    # El service ya notificó por WebSocket; aquí no se vuelve a emitir.
    return asdict(comanda)


@router.websocket("/ws")
async def comandas_ws(
    websocket: WebSocket,
    ticket: str | None = Query(None),
    token: str | None = Query(None),
) -> None:
    """Canal en tiempo real de comandas: emite comanda_creada/comanda_actualizada
    a los clientes de la sucursal correspondiente (ver app/core/ws_manager.py).

    El ticket efímero (?ticket=..., ver POST /auth/ws-ticket) reemplaza
    al JWT crudo en la URL; ?token=... se sigue aceptando mientras
    settings.WS_ACEPTA_JWT sea true. Va por query param porque el handshake WS
    nativo del navegador no admite headers custom."""
    # La conexión a la BD solo se usa para autenticar y se suelta antes de
    # quedarse escuchando: el socket puede durar horas (ver get_db).
    try:
        async with conexion_breve() as conn:
            current_user = await resolve_ws_auth(conn, ticket, token)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    except TimeoutError:
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
        return

    if not has_permission(current_user.role, "restaurante:ver_pedidos"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    scope = sucursal_scope(current_user)
    canal = scope if scope is not None else CANAL_GLOBAL

    await manager.connect(canal, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(canal, websocket)
    except Exception:
        logger.debug("Conexion WS de comandas cerrada con error", exc_info=True)
        manager.disconnect(canal, websocket)
