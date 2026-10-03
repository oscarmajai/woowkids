"""
app/services/compra_service.py
Lógica de negocio para compras a proveedor. Al recibir una compra convierte
cada línea a la unidad base del insumo y genera movimientos de entrada
(fase 3). SAD §3.2: el service orquesta repositorios, nunca escribe SQL
directamente.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from app.exceptions import Conflicto, DatosInvalidos, NoEncontrado, RecepcionInvalidaError
from app.exceptions.inventario import CantidadFueraDeRangoError, RecursoInactivoError
from app.repositories import (
    compra_repository,
    insumo_repository,
    movimiento_inventario_repository,
    presentacion_insumo_repository,
    proveedor_repository,
    unidad_medida_repository,
)
from app.schemas.compra import (
    CompraCrear,
    CompraEditar,
    CompraOut,
    CompraUpdate,
    LineaRecepcion,
    RecibirCompraRequest,
)
from app.schemas.limites_inventario import MAX_CANTIDAD, MIN_CANTIDAD
from app.services import costeo_service


async def _construir_out(conn: asyncpg.Connection, compra: dict[str, Any]) -> CompraOut:
    detalles = await compra_repository.listar_detalles(conn, compra["id"])
    return CompraOut.model_validate({**compra, "detalles": detalles})


def _validar_proveedor_activo(proveedor: dict[str, Any]) -> None:
    """M22: un proveedor eliminado (borrado lógico) no admite compras nuevas."""
    if not proveedor["activo"]:
        raise RecursoInactivoError(
            f"El proveedor «{proveedor['nombre']}» está eliminado; no se le pueden "
            "registrar compras."
        )


def _validar_insumo_activo(insumo: dict[str, Any]) -> None:
    """M22: un insumo eliminado (borrado lógico) no se puede comprar."""
    if not insumo["activo"]:
        raise RecursoInactivoError(
            f"El insumo «{insumo['nombre']}» está eliminado; no se puede agregar a una compra."
        )


def _validar_cantidad_base(cantidad_base: Decimal, insumo: dict[str, Any]) -> None:
    """M3: la cantidad convertida a la unidad base es la que se suma al stock
    (numeric(12,3)). Una línea válida en su unidad puede salirse de rango al
    convertirla (9,999,999 kg = 9,999,999,000 g) o redondearse a 0 (0.0004 g):
    antes eso daba 500 al recibir."""
    if cantidad_base < MIN_CANTIDAD or cantidad_base > MAX_CANTIDAD:
        raise CantidadFueraDeRangoError(
            f"La cantidad de «{insumo['nombre']}» convertida a su unidad base "
            f"({cantidad_base.normalize():f}) está fuera de rango: debe ser de "
            f"{MIN_CANTIDAD} a {MAX_CANTIDAD:,}."
        )


async def _validar_unidad_compatible(
    conn: asyncpg.Connection, unidad_medida_id: UUID, insumo: dict[str, Any]
) -> None:
    unidad_linea = await unidad_medida_repository.obtener(conn, unidad_medida_id)
    unidad_base = await unidad_medida_repository.obtener(conn, insumo["unidad_base_id"])
    if not unidad_linea or not unidad_base:
        raise DatosInvalidos("Unidad de medida inválida.")
    if unidad_linea["tipo"] != unidad_base["tipo"]:
        raise DatosInvalidos(
            f"La unidad de la línea no es compatible con la unidad base de «{insumo['nombre']}»."
        )


async def _validar_y_calcular_base(
    conn: asyncpg.Connection,
    insumo: dict[str, Any],
    unidad_medida_id: UUID | None,
    presentacion_id: UUID | None,
    cantidad: Decimal,
    costo_unitario: Decimal,
) -> tuple[Decimal, Decimal]:
    """Valida la línea y devuelve (cantidad_base, costo_base) expresados en
    la unidad_base_id del insumo. Se bifurca según cuál campo trae la línea:
    unidad_medida_id (factor global entre unidades) o presentacion_id
    (equivalencia directa y específica del insumo, fase 7)."""
    if presentacion_id is not None:
        presentacion = await presentacion_insumo_repository.obtener(conn, presentacion_id)
        if not presentacion:
            raise DatosInvalidos("La presentación indicada no existe.")
        if presentacion["insumo_id"] != insumo["id"] or not presentacion["activo"]:
            raise DatosInvalidos(
                f"La presentación indicada no pertenece a «{insumo['nombre']}» o está inactiva."
            )
        equivalencia = presentacion["equivalencia_base"]
        _validar_cantidad_base(cantidad * equivalencia, insumo)
        return cantidad * equivalencia, costo_unitario / equivalencia

    assert unidad_medida_id is not None
    await _validar_unidad_compatible(conn, unidad_medida_id, insumo)
    unidad_linea = await unidad_medida_repository.obtener(conn, unidad_medida_id)
    unidad_base = await unidad_medida_repository.obtener(conn, insumo["unidad_base_id"])
    assert unidad_linea is not None and unidad_base is not None
    factor = unidad_linea["factor_a_base"] / unidad_base["factor_a_base"]
    _validar_cantidad_base(cantidad * factor, insumo)
    return cantidad * factor, costo_unitario / factor


async def crear(conn: asyncpg.Connection, body: CompraCrear, creado_por: UUID) -> CompraOut:
    proveedor = await proveedor_repository.obtener(conn, body.proveedor_id)
    if not proveedor:
        raise NoEncontrado("Proveedor")
    if proveedor["sucursal_id"] != body.sucursal_id:
        raise DatosInvalidos("El proveedor no pertenece a esta sucursal.")
    _validar_proveedor_activo(proveedor)

    for detalle in body.detalles:
        insumo = await insumo_repository.obtener(conn, detalle.insumo_id)
        if not insumo:
            raise NoEncontrado("Insumo")
        if insumo["sucursal_id"] != body.sucursal_id:
            raise DatosInvalidos("El insumo no pertenece a esta sucursal.")
        _validar_insumo_activo(insumo)
        await _validar_y_calcular_base(
            conn,
            insumo,
            detalle.unidad_medida_id,
            detalle.presentacion_id,
            detalle.cantidad,
            detalle.costo_unitario,
        )

    compra_id = await compra_repository.crear_con_detalles(
        conn,
        body.sucursal_id,
        body.proveedor_id,
        body.notas,
        body.detalles,
        creado_por,
        iva=body.iva,
    )
    return await obtener(conn, compra_id)


async def obtener(conn: asyncpg.Connection, compra_id: UUID) -> CompraOut:
    row = await compra_repository.obtener(conn, compra_id)
    if not row:
        raise NoEncontrado("Compra")
    return await _construir_out(conn, row)


async def listar(conn: asyncpg.Connection, sucursal_id: UUID | None = None) -> list[CompraOut]:
    rows = await compra_repository.listar(conn, sucursal_id)
    return [CompraOut.model_validate(r) for r in rows]


async def actualizar(conn: asyncpg.Connection, compra_id: UUID, body: CompraUpdate) -> CompraOut:
    updates = body.model_dump(exclude_unset=True)
    async with conn.transaction():
        # Bajo el mismo bloqueo que recibir/cancelar (C5): el estado que se
        # revisa abajo no puede cambiar antes del UPDATE.
        compra = await compra_repository.bloquear(conn, compra_id)
        if not compra:
            raise NoEncontrado("Compra")
        # B10: `activo=false` sobre una compra con mercancía recibida respondía
        # 200 sin efecto (la compra seguía en el listado y el stock no se
        # revertía). Una compra recibida no se desactiva; una pendiente se
        # cancela con POST /compras/{id}/cancelar.
        if "activo" in updates and compra["estado"] in ("R", "PARCIAL"):
            raise Conflicto(
                "Una compra recibida o con recepción parcial no se puede desactivar: "
                "su mercancía ya entró al inventario."
            )
        row = await compra_repository.actualizar(conn, compra_id, updates)
    if not row:
        raise NoEncontrado("Compra")
    return await _construir_out(conn, row)


async def editar(conn: asyncpg.Connection, compra_id: UUID, body: CompraEditar) -> CompraOut:
    """Reemplaza proveedor, notas y líneas de una compra que sigue en 'P'."""
    # C5: bajo el bloqueo de la compra, para que una recepción simultánea no
    # quede registrada sobre líneas que esta edición borra y reinserta.
    async with conn.transaction():
        compra = await compra_repository.bloquear(conn, compra_id)
        if not compra:
            raise NoEncontrado("Compra")
        if compra["estado"] != "P":
            raise Conflicto("Solo se puede editar una compra pendiente.")

        proveedor = await proveedor_repository.obtener(conn, body.proveedor_id)
        if not proveedor or proveedor["sucursal_id"] != compra["sucursal_id"]:
            raise DatosInvalidos("El proveedor no pertenece a esta sucursal.")
        _validar_proveedor_activo(proveedor)
        for detalle in body.detalles:
            insumo = await insumo_repository.obtener(conn, detalle.insumo_id)
            if not insumo:
                raise NoEncontrado("Insumo")
            if insumo["sucursal_id"] != compra["sucursal_id"]:
                raise DatosInvalidos("El insumo no pertenece a esta sucursal.")
            _validar_insumo_activo(insumo)
            await _validar_y_calcular_base(
                conn,
                insumo,
                detalle.unidad_medida_id,
                detalle.presentacion_id,
                detalle.cantidad,
                detalle.costo_unitario,
            )

        await compra_repository.reemplazar_detalles(conn, compra_id, body)
    return await obtener(conn, compra_id)


def _conflicto_por_estado(estado: str) -> Conflicto:
    if estado == "R":
        return Conflicto("La compra ya fue recibida.")
    if estado == "C":
        return Conflicto("La compra está cancelada.")
    return Conflicto("La compra ya fue recibida o está cancelada.")


def _fmt(cantidad: Decimal) -> str:
    return f"{cantidad.normalize():f}"


def cantidades_a_recibir(
    detalles: list[dict[str, Any]], lineas: list[LineaRecepcion] | None
) -> dict[UUID, Decimal]:
    """Cuánto recibir de cada línea en esta vuelta, ya validado. Solo devuelve
    las líneas con cantidad > 0.

    - `lineas is None`: todo lo pendiente de cada línea (recibir completa).
    - Con `lineas`: lo que diga cada una; una línea de la compra que no venga
      cuenta como 0 (A12: antes se recibía completa). Pedir más de lo pendiente
      (M23: antes se recortaba en silencio), un detalle ajeno a la compra o
      repetido responde 422 sin tocar nada.

    Lanza Conflicto si la compra ya no tiene nada pendiente."""
    pendientes = {d["id"]: d["cantidad"] - d["cantidad_recibida"] for d in detalles}
    if not any(p > 0 for p in pendientes.values()):
        raise Conflicto("No hay nada pendiente por recibir en esta compra.")

    if lineas is None:
        return {detalle_id: p for detalle_id, p in pendientes.items() if p > 0}

    por_id = {d["id"]: d for d in detalles}
    resultado: dict[UUID, Decimal] = {}
    vistos: set[UUID] = set()
    for linea in lineas:
        detalle = por_id.get(linea.detalle_id)
        if detalle is None:
            raise RecepcionInvalidaError(
                "Una de las líneas a recibir no pertenece a esta compra.",
                {"detalle_id": str(linea.detalle_id)},
            )
        if linea.detalle_id in vistos:
            raise RecepcionInvalidaError(
                f"La línea de «{detalle['insumo_nombre']}» viene repetida en la recepción.",
                {"detalle_id": str(linea.detalle_id), "insumo_nombre": detalle["insumo_nombre"]},
            )
        vistos.add(linea.detalle_id)
        pendiente = max(pendientes[linea.detalle_id], Decimal("0"))
        if linea.cantidad > pendiente:
            raise RecepcionInvalidaError(
                f"La cantidad a recibir de «{detalle['insumo_nombre']}» "
                f"({_fmt(linea.cantidad)}) excede lo pendiente ({_fmt(pendiente)}).",
                {
                    "detalle_id": str(linea.detalle_id),
                    "insumo_nombre": detalle["insumo_nombre"],
                    "solicitado": _fmt(linea.cantidad),
                    "pendiente": _fmt(pendiente),
                },
            )
        if linea.cantidad > 0:
            resultado[linea.detalle_id] = linea.cantidad

    if not resultado:
        raise RecepcionInvalidaError("Indica al menos una cantidad mayor a 0 para recibir.")
    return resultado


async def recibir(
    conn: asyncpg.Connection,
    compra_id: UUID,
    creado_por: UUID,
    body: RecibirCompraRequest | None = None,
) -> CompraOut:
    lineas = body.lineas if body else None

    async with conn.transaction():
        # C5: bloquear la compra y releer estado, detalles y pendientes DENTRO de
        # la transacción. Antes se leían fuera y sin bloqueo: N recepciones
        # simultáneas veían el mismo pendiente y sumaban el stock N veces. Ahora
        # la segunda espera a que la primera confirme y ve la compra ya recibida
        # (409) o solo lo que quedó pendiente (recepción parcial).
        compra = await compra_repository.bloquear(conn, compra_id)
        if not compra:
            raise NoEncontrado("Compra")
        if compra["estado"] not in ("P", "PARCIAL"):
            raise _conflicto_por_estado(compra["estado"])

        detalles = await compra_repository.listar_detalles(conn, compra_id)
        # Se valida TODA la recepción antes de mover stock: una línea inválida
        # no deja aplicadas a medias las anteriores.
        a_recibir = cantidades_a_recibir(detalles, lineas)
        for detalle in detalles:
            recibir_ahora = a_recibir.get(detalle["id"])
            if recibir_ahora is None:
                continue

            insumo = await insumo_repository.obtener(conn, detalle["insumo_id"])
            if not insumo:
                raise NoEncontrado("Insumo")
            cantidad_base, costo_base = await _validar_y_calcular_base(
                conn,
                insumo,
                detalle["unidad_medida_id"],
                detalle["presentacion_id"],
                recibir_ahora,
                detalle["costo_unitario"],
            )
            nuevo_stock = await insumo_repository.ajustar_stock(
                conn, detalle["insumo_id"], cantidad_base
            )
            if nuevo_stock is None:
                raise RuntimeError("No se pudo aumentar el stock del insumo al recibir la compra")
            await costeo_service.registrar_entrada(
                conn, detalle["insumo_id"], cantidad_base, costo_base, "compra", compra_id
            )
            await movimiento_inventario_repository.registrar(
                conn,
                sucursal_id=compra["sucursal_id"],
                insumo_id=detalle["insumo_id"],
                tipo="E",
                cantidad=cantidad_base,
                stock_resultante=nuevo_stock,
                motivo="compra",
                referencia_id=compra_id,
                notas=None,
                creado_por=creado_por,
                costo_total=cantidad_base * costo_base,
            )
            await compra_repository.sumar_recepcion_linea(conn, detalle["id"], recibir_ahora)

        detalles = await compra_repository.listar_detalles(conn, compra_id)
        completa = all(d["cantidad_recibida"] >= d["cantidad"] for d in detalles)
        actualizada = await compra_repository.marcar_estado(
            conn, compra_id, "R" if completa else "PARCIAL", estados_previos=("P", "PARCIAL")
        )
        if actualizada is None:
            raise Conflicto("La compra ya fue recibida o está cancelada.")

    return await _construir_out(conn, actualizada)


async def cancelar(conn: asyncpg.Connection, compra_id: UUID) -> CompraOut:
    # C5: mismo bloqueo que recibir. El UPDATE condicionado de marcar_cancelada ya
    # impedía cancelar una compra recibida, pero sin el bloqueo una cancelación que
    # llegaba durante una recepción podía responder con el estado viejo.
    async with conn.transaction():
        compra = await compra_repository.bloquear(conn, compra_id)
        if not compra:
            raise NoEncontrado("Compra")
        if compra["estado"] != "P":
            raise Conflicto("Solo se puede cancelar una compra pendiente sin recepciones.")
        cancelada = await compra_repository.marcar_cancelada(conn, compra_id)
        if cancelada is None:
            raise Conflicto("La compra ya fue recibida o está cancelada.")
    return await _construir_out(conn, cancelada)
