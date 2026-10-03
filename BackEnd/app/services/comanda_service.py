"""
app/services/comanda_service.py
Lógica de negocio para comandas.
SAD §3.2: el service orquesta repositorios, nunca escribe SQL directamente.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, cast
from uuid import UUID, uuid4

import asyncpg

from app.core.scope import sucursal_scope
from app.core.ws_manager import manager
from app.exceptions.comandas import (
    AutorizacionAdminRequeridaError,
    ComandaCanceladaError,
    ComandaPagadaRequiereCancelacionError,
    TransicionComandaInvalidaError,
)
from app.models.comanda import Comanda, DetalleComanda
from app.repositories import comanda_repository, producto_repository
from app.repositories.caja_repository import registrar_movimiento_caja
from app.schemas.auth import TokenData
from app.schemas.comanda import ComandaCreate
from app.services import (
    devolucion_service,
    inventario_service,
    lealtad_service,
    precios_venta,
    turnos_caja_service,
)


def _producto_id_de_detalle(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("producto_id") or item["id"])
    if hasattr(item, "producto_id") and hasattr(item, "comanda_id"):
        return str(item.producto_id)
    return str(item.id)


def _cantidad_de_detalle(item: Any) -> int:
    return int(item["cantidad"]) if isinstance(item, dict) else int(item.cantidad)


def _detalle_a_dict(item: Any, nombre: str) -> dict[str, Any]:
    if isinstance(item, dict):
        detalle = dict(item)
    elif hasattr(item, "model_dump"):
        detalle = item.model_dump()
    else:
        detalle = asdict(item)
    detalle["nombre"] = nombre
    return detalle


async def expandir_detalles_comanda(
    conn: asyncpg.Connection, detalles: list[Any]
) -> list[DetalleComanda | dict[str, Any]]:
    """Convierte los detalles con combos en detalles individuales (uno por
    producto hijo), para que cocina sepa exactamente qué preparar."""
    detalles_finales: list[DetalleComanda | dict[str, Any]] = []

    # Pre-computar: ¿qué combos ya tienen hijos en la lista?
    hijos_existentes = set()
    for d in detalles:
        padre = getattr(d, "es_hijo_de", None) or (
            d.get("es_hijo_de") if isinstance(d, dict) else None
        )
        if padre:
            hijos_existentes.add(padre)

    for item in detalles:
        producto_id = _producto_id_de_detalle(item)

        if await producto_repository.es_producto_combo(conn, producto_id):
            if producto_id in hijos_existentes:
                continue
            else:
                producto_padre = await producto_repository.get_by_id(conn, producto_id)
                nombre_padre = producto_padre["nombre"] if producto_padre else ""
                hijos = await producto_repository.get_combo_hijos(conn, producto_id)
                cantidad_pedida = _cantidad_de_detalle(item)

                # Una instancia por unidad pedida: cada combo se expande en su
                # propio set de hijos con id_combo_padre único, para que el
                # visor de cocina pueda separar combos múltiples por unidad.
                for _unidad in range(cantidad_pedida):
                    id_instancia = str(uuid4())
                    for hijo in hijos:
                        h_id = str(hijo["producto_id"])
                        hijo_producto = await producto_repository.get_by_id(conn, h_id)
                        nombre_hijo = hijo_producto["nombre"] if hijo_producto else ""
                        detalles_finales.append(
                            {
                                "producto_id": str(hijo["producto_id"]),
                                "nombre": nombre_hijo,
                                "nombre_combo_padre": nombre_padre,
                                "cantidad": hijo["cantidad"],
                                "precio_unitario": 0,
                                "subtotal": 0,
                                "es_hijo_de": producto_id,
                                "es_hijo_combo": True,
                                "notas_especiales": None,
                                "id_combo_padre": id_instancia,
                            }
                        )
        else:
            producto_info = await producto_repository.get_by_id(conn, producto_id)
            nombre_producto = producto_info["nombre"] if producto_info else ""
            detalle = _detalle_a_dict(item, nombre_producto)

            # Un ítem pertenece a un combo SOLO si la orden lo trajo así
            # (campos persistidos es_hijo_de/nombre_combo_padre/es_hijo_combo).
            # Nunca se infiere desde el catálogo global de combos: un producto
            # que es integrante de un combo pero se vendió suelto debe salir
            # limpio, sin etiquetas de paquete que no le corresponden.
            if not detalle.get("nombre_combo_padre"):
                detalle["nombre_combo_padre"] = None
                detalle["es_hijo_de"] = None
                detalle["es_hijo_combo"] = False

            detalles_finales.append(detalle)

    return detalles_finales


async def crear_comanda(
    conn: asyncpg.Connection,
    comanda_in: ComandaCreate,
    current_user: TokenData,
    apertura_caja_id: str | None,
) -> Comanda:
    """Crea una comanda, descuenta el stock de los insumos de la receta de
    cada producto vendido (aborta todo si alguno no alcanza), registra el
    movimiento de venta en la caja del turno activo, la reexpande desde BD
    y notifica a los clientes conectados.

    `apertura_caja_id=None` crea la comanda SIN movimiento de venta en caja: lo
    usan las comandas automáticas de eventos, cuyo ingreso ya se cobró como
    anticipo/liquidación en pagos_reservacion (registrarlo aquí lo contaría dos
    veces y descuadraría el arqueo).

    metodo_pago_id va en None temporalmente: el módulo de métodos de pago para
    comandas todavía no está integrado (columna nullable a propósito mientras tanto).
    """
    creado_por = str(UUID(current_user.sub))

    async with conn.transaction():
        if apertura_caja_id is not None:
            # N1: el turno debe seguir ABIERTA bajo bloqueo hasta que la venta
            # confirme.
            await turnos_caja_service.bloquear_turno_para_cobro(conn, apertura_caja_id)
        comanda = await comanda_repository.crear_comanda_con_detalles(
            conn, comanda_in, None, creado_por
        )
        await inventario_service.descontar_por_venta(
            conn,
            str(comanda_in.sucursal_id),
            comanda_in.detalles_comanda,
            comanda.id,
            UUID(current_user.sub),
        )
        if apertura_caja_id is not None:
            await registrar_movimiento_caja(
                conn,
                apertura_caja_id=apertura_caja_id,
                tipo_movimiento="O",
                referencia_id=comanda.id,
                metodo_pago_id=None,
                monto=comanda.total_final,
                creado_por=creado_por,
            )

    comanda.detalles = await expandir_detalles_comanda(conn, comanda.detalles)
    await manager.broadcast(
        comanda.sucursal_id, {"type": "comanda_creada", "comanda": asdict(comanda)}
    )
    return comanda


async def crear_comanda_pos(
    conn: asyncpg.Connection,
    comanda_in: ComandaCreate,
    current_user: TokenData,
    apertura_caja_id: str,
) -> Comanda:
    """POST /comandas: como crear_comanda, pero con los precios y el total
    recalculados con el catálogo de la sucursal (C2); 409 si el cliente
    mandó otros. Las comandas automáticas de eventos no pasan por aquí: usan
    el precio del paquete, no el del catálogo."""
    sucursal_id = UUID(str(comanda_in.sucursal_id))
    venta = await precios_venta.calcular_venta(conn, sucursal_id, comanda_in.detalles_comanda)
    precios_venta.verificar_total(comanda_in.total_final, venta.subtotal)
    comanda_in = comanda_in.model_copy(
        update={"detalles_comanda": venta.detalles, "total_final": venta.subtotal}
    )
    return await crear_comanda(conn, comanda_in, current_user, apertura_caja_id)


async def listar_pendientes(conn: asyncpg.Connection, current_user: TokenData) -> list[Comanda]:
    scope = sucursal_scope(current_user)
    comandas = await comanda_repository.get_comandas_pendientes(conn, scope)

    for comanda in comandas:
        comanda.detalles = await expandir_detalles_comanda(conn, comanda.detalles)

    return comandas


# A2: máquina de estados de la comanda. Solo avanza un paso a la vez
# (P → E → L → T) y se cancela (C) desde los estados en que sigue en cocina.
# T (entregada) y C (cancelada) son terminales: lo entregado ya consumió sus
# insumos, así que no se cancela ni se revierte su stock.
ESTADOS_COMANDA = frozenset({"P", "E", "L", "T", "C"})
_SIGUIENTE_ESTADO = {"P": "E", "E": "L", "L": "T"}
_ESTADOS_CANCELABLES = frozenset({"P", "E", "L"})
_NOMBRE_ESTADO = {
    "P": "Pendiente",
    "E": "En preparación",
    "L": "Lista",
    "T": "Entregada",
    "C": "Cancelada",
}


def _nombre_estado(estado: str) -> str:
    return _NOMBRE_ESTADO.get(estado, estado or "sin estado")


def validar_transicion(estado_actual: str, activo: bool, nuevo_estado: str) -> None:
    """Lanza 409 si la comanda no puede pasar de `estado_actual` a `nuevo_estado`.
    Una comanda cancelada o inactiva ya no admite ningún cambio (antes volvía
    al tablero de cocina como "zombie" y un C → T → C revertía el stock dos
    veces)."""
    if not activo or estado_actual == "C":
        raise ComandaCanceladaError()
    if nuevo_estado == "C":
        if estado_actual not in _ESTADOS_CANCELABLES:
            raise TransicionComandaInvalidaError(
                f"Una comanda «{_nombre_estado(estado_actual)}» ya no se puede cancelar."
            )
        return
    if _SIGUIENTE_ESTADO.get(estado_actual) != nuevo_estado:
        siguiente = _SIGUIENTE_ESTADO.get(estado_actual)
        detalle = (
            f" El siguiente paso es «{_nombre_estado(siguiente)}»."
            if siguiente
            else " Ya no avanza a ningún otro estado."
        )
        raise TransicionComandaInvalidaError(
            f"No se puede pasar una comanda de «{_nombre_estado(estado_actual)}» a "
            f"«{_nombre_estado(nuevo_estado)}».{detalle}"
        )


async def cambiar_estado(
    conn: asyncpg.Connection,
    comanda_id: str,
    nuevo_estado: str,
    current_user: TokenData,
    motivo_cancelacion: str | None = None,
    token_pin_admin: str | None = None,
) -> Comanda | None:
    """
    Cambia el estado de una comanda siguiendo la máquina de estados (A2) y
    notifica a los clientes conectados (una sola vez, M27). Registra auditoría
    (modificado, modificado_por). Retorna None si la comanda no existe.

    Cancelar ('C') exige motivo, desactiva la comanda y revierte el stock y
    los puntos de lealtad. Todo bajo el bloqueo de la fila de la comanda: la
    reversión ocurre una sola vez aunque lleguen cancelaciones simultáneas.
    Si la comanda tiene pagos (A4), además exige `token_pin_admin` (PIN de un
    administrador de la sucursal) y registra la devolución en el turno de
    caja abierto de quien cancela (ver devolucion_service).
    """
    if nuevo_estado not in ESTADOS_COMANDA:
        raise ValueError(f"Estado de comanda inválido: «{nuevo_estado}».")
    usuario_id = str(UUID(current_user.sub))

    # Validación previa sin bloqueo, para responder rápido y en orden
    # (transición, motivo, caja, autorización) antes de pedir el PIN.
    previo = await comanda_repository.get_estado_comanda(conn, comanda_id)
    if previo is None:
        return None
    validar_transicion(previo["estado_actual"], previo["activo"], nuevo_estado)

    es_cancelacion = nuevo_estado == "C"
    plan: devolucion_service.PlanDevolucion | None = None
    if es_cancelacion:
        if not motivo_cancelacion or not motivo_cancelacion.strip():
            raise ValueError("El motivo de cancelación es obligatorio al cancelar una comanda.")
        plan = await devolucion_service.planear(conn, comanda_id, usuario_id)
        if plan is not None and not token_pin_admin:
            raise AutorizacionAdminRequeridaError(plan.apertura_cancelador_id)

    async with conn.transaction():
        if plan is not None:
            await devolucion_service.bloquear_turnos(conn, plan)
        actual = await comanda_repository.bloquear_comanda(conn, comanda_id)
        if actual is None:
            return None
        # Otra petición pudo cambiarla mientras esperábamos el bloqueo.
        validar_transicion(actual["estado_actual"], actual["activo"], nuevo_estado)

        sucursal_id = str(actual["sucursal_id"])
        detalles: list[DetalleComanda] = []
        if es_cancelacion:
            # Detalles leídos ya con la comanda bloqueada (siempre DetalleComanda,
            # antes de pasar por expandir_detalles_comanda).
            bloqueada = await comanda_repository.get_comanda_por_id(conn, comanda_id)
            if bloqueada is not None:
                detalles = cast(list[DetalleComanda], bloqueada.detalles)
            if plan is not None:
                await devolucion_service.registrar(
                    conn,
                    plan,
                    comanda_id=comanda_id,
                    sucursal_id=sucursal_id,
                    token_pin_admin=cast(str, token_pin_admin),
                    usuario_id=usuario_id,
                )

        comanda = await comanda_repository.actualizar_estado_comanda(
            conn,
            comanda_id,
            nuevo_estado,
            usuario_id,
            motivo_cancelacion=motivo_cancelacion,
            desactivar=es_cancelacion,
        )
        if comanda is not None and es_cancelacion:
            await inventario_service.revertir_por_cancelacion(
                conn, sucursal_id, detalles, comanda_id, UUID(usuario_id)
            )
            await lealtad_service.revertir_por_cancelacion(conn, UUID(comanda_id), UUID(usuario_id))

    if comanda is not None:
        comanda.detalles = await expandir_detalles_comanda(conn, comanda.detalles)
        await manager.broadcast(
            comanda.sucursal_id, {"type": "comanda_actualizada", "comanda": asdict(comanda)}
        )
    return comanda


async def modificar_comanda_parcial(
    conn: asyncpg.Connection,
    comanda_id: str,
    detalles_ids_a_eliminar: list[str],
    usuario_id: str | None = None,
    motivo_cancelacion: str | None = None,
) -> Comanda | None:
    """Elimina productos de una comanda en estado 'P' y recalcula el total.

    Si se eliminan todos los productos, cancela automáticamente la comanda
    y requiere motivo_cancelacion.

    Retorna None si la comanda no existe o no está en estado 'P'.
    Notifica a cocina vía WebSocket después de la modificación.

    A4: quitar todos los productos de una comanda cobrada equivale a
    cancelarla, y eso exige la autorización y la devolución de cambiar_estado:
    responde 409 para que el cliente use ese flujo.
    """
    actual = await comanda_repository.get_comanda_por_id(conn, comanda_id)
    if actual is not None:
        detalles = cast(list[DetalleComanda], actual.detalles)
        restantes = {d.id for d in detalles} - set(detalles_ids_a_eliminar)
        if not restantes and await devolucion_service.comanda_tiene_pagos(conn, comanda_id):
            raise ComandaPagadaRequiereCancelacionError()

    comanda = await comanda_repository.modificar_comanda_parcial(
        conn,
        comanda_id,
        detalles_ids_a_eliminar,
        usuario_id,
        motivo_cancelacion,
    )
    if comanda is not None:
        comanda.detalles = await expandir_detalles_comanda(conn, comanda.detalles)
        await manager.broadcast(
            comanda.sucursal_id, {"type": "comanda_actualizada", "comanda": asdict(comanda)}
        )
    return comanda


async def obtener_por_id(
    conn: asyncpg.Connection,
    comanda_id: str,
) -> Comanda | None:
    """Retorna una comanda por su ID, o None si no existe."""
    return await comanda_repository.get_comanda_por_id(conn, comanda_id)
