"""Precios de venta del punto de venta calculados en el servidor (C2).

El navegador manda el pedido (producto, cantidad y lo que cree que cuesta),
pero el precio que se cobra sale siempre del catálogo de la sucursal de la
sesión, el mismo que muestra el POS en GET /productos/catalogo. Si lo que
mandó el cliente no coincide, se rechaza con 409 y no se cobra nada: así el
cajero ve el precio nuevo antes de cobrar, en vez de que el ticket cambie
sin avisar.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

import asyncpg

from app.exceptions import PedidoInvalidoError, PrecioCambiadoError, ProductoNoDisponibleError
from app.repositories import producto_repository
from app.schemas.comanda import DetalleCreate

CENTAVO = Decimal("0.01")

# Tope por renglón: evita cantidades absurdas (1e9 piezas) que solo pueden
# venir de una petición manipulada o de un error de captura.
CANTIDAD_MAXIMA_POR_RENGLON = 999

# Tipos que el POS vende sueltos (alimentos y bebidas); los combos se aceptan
# por su bandera es_combo. Igual que producto_repository.get_catalogo_venta_by_sucursal.
TIPOS_VENDIBLES_POS = frozenset({"A", "B"})


@dataclass(frozen=True)
class VentaCalculada:
    """Detalles normalizados (precios del catálogo, hijos de combo a $0) y
    subtotal bruto calculado por el servidor, antes de descuentos."""

    detalles: list[DetalleCreate]
    subtotal: Decimal


def a_centavos(valor: Decimal | float | int) -> Decimal:
    return Decimal(str(valor)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def formatear_pesos(valor: Decimal) -> str:
    return f"${a_centavos(valor):,.2f}"


def _uuid_o_error(valor: str | None, que: str) -> UUID:
    try:
        return UUID(str(valor))
    except (TypeError, ValueError) as exc:
        raise PedidoInvalidoError(f"El {que} «{valor}» no es un identificador válido.") from exc


def _validar_cantidad(detalle: DetalleCreate) -> None:
    if not 1 <= detalle.cantidad <= CANTIDAD_MAXIMA_POR_RENGLON:
        raise PedidoInvalidoError(
            f"La cantidad de «{detalle.nombre}» debe estar entre 1 y "
            f"{CANTIDAD_MAXIMA_POR_RENGLON}."
        )


def _producto_de_la_sucursal(
    catalogo: dict[UUID, dict[str, Any]], producto_id: UUID, sucursal_id: UUID
) -> dict[str, Any]:
    producto = catalogo.get(producto_id)
    # Un producto de otra sucursal se reporta igual que uno inexistente: el
    # cajero no tiene por qué saber qué vende otra sucursal.
    if producto is None or producto["sucursal_id"] != sucursal_id:
        raise PedidoInvalidoError(
            "Uno de los productos del pedido no existe en esta sucursal. Actualiza el pedido.",
            code="PRODUCTO_INVALIDO",
        )
    return producto


def _normalizar_renglon(
    detalle: DetalleCreate, producto: dict[str, Any], producto_id: UUID
) -> DetalleCreate:
    nombre = producto["nombre"]
    if not producto["activo"]:
        raise ProductoNoDisponibleError(nombre)
    if producto["tipo"] not in TIPOS_VENDIBLES_POS and not producto["es_combo"]:
        raise PedidoInvalidoError(
            f"«{nombre}» no se vende en el punto de venta.", code="PRODUCTO_INVALIDO"
        )

    precio = a_centavos(producto["precio_unitario"])
    if a_centavos(detalle.precio_unitario) != precio:
        raise PrecioCambiadoError(
            f"El precio de «{nombre}» cambió a {formatear_pesos(precio)}. Actualiza el pedido."
        )
    importe = precio * detalle.cantidad
    if a_centavos(detalle.subtotal) != importe:
        raise PrecioCambiadoError(
            f"El importe de «{nombre}» ({detalle.cantidad} x {formatear_pesos(precio)}) "
            f"es {formatear_pesos(importe)}. Actualiza el pedido."
        )

    return DetalleCreate(
        id=str(producto_id),
        nombre=nombre,
        cantidad=detalle.cantidad,
        precio_unitario=precio,
        subtotal=importe,
        notas_especiales=detalle.notas_especiales,
    )


def _validar_hijos_combo(
    hijos: list[DetalleCreate],
    unidades_por_combo: dict[UUID, int],
    definiciones: dict[UUID, dict[UUID, int]],
    catalogo: dict[UUID, dict[str, Any]],
) -> list[DetalleCreate]:
    """Los renglones hijo (es_hijo_combo) son informativos para cocina y el
    ticket: no cobran ni descuentan inventario. Por eso tienen que ser
    exactamente la definición del combo (producto_combo), una instancia
    (id_combo_padre) por unidad vendida; si no, un renglón "hijo" serviría
    para sacar de cocina un producto gratis."""
    instancias: dict[UUID, tuple[UUID, dict[UUID, int]]] = {}
    for hijo in hijos:
        combo_id = _uuid_o_error(hijo.es_hijo_de, "combo del renglón")
        if combo_id not in unidades_por_combo:
            raise PedidoInvalidoError(
                "Un producto del combo no corresponde a ningún combo del pedido.",
                code="COMBO_INVALIDO",
            )
        instancia_id = _uuid_o_error(hijo.id_combo_padre, "renglón del combo")
        combo_de_instancia, contenido = instancias.setdefault(instancia_id, (combo_id, {}))
        if combo_de_instancia != combo_id:
            raise PedidoInvalidoError(
                "Un renglón del combo pertenece a dos combos distintos.", code="COMBO_INVALIDO"
            )
        producto_id = _uuid_o_error(hijo.id, "producto")
        contenido[producto_id] = contenido.get(producto_id, 0) + hijo.cantidad

    instancias_por_combo: dict[UUID, int] = {}
    for combo_id, contenido in instancias.values():
        if contenido != definiciones.get(combo_id, {}):
            nombre_combo = catalogo[combo_id]["nombre"]
            raise PedidoInvalidoError(
                f"Los productos del combo «{nombre_combo}» no coinciden con su "
                "definición. Actualiza el pedido.",
                code="COMBO_INVALIDO",
            )
        instancias_por_combo[combo_id] = instancias_por_combo.get(combo_id, 0) + 1

    # Sin hijos, el servidor expande el combo él solo (expandir_detalles_comanda);
    # si vienen, tiene que haber uno por cada unidad vendida.
    for combo_id, n_instancias in instancias_por_combo.items():
        if n_instancias != unidades_por_combo[combo_id]:
            nombre_combo = catalogo[combo_id]["nombre"]
            raise PedidoInvalidoError(
                f"El combo «{nombre_combo}» trae {n_instancias} juego(s) de productos "
                f"para {unidades_por_combo[combo_id]} unidad(es). Actualiza el pedido.",
                code="COMBO_INVALIDO",
            )

    normalizados: list[DetalleCreate] = []
    for hijo in hijos:
        combo_id = UUID(str(hijo.es_hijo_de))
        producto = catalogo.get(UUID(hijo.id))
        normalizados.append(
            DetalleCreate(
                id=hijo.id,
                nombre=producto["nombre"] if producto else hijo.nombre,
                cantidad=hijo.cantidad,
                precio_unitario=Decimal("0"),
                subtotal=Decimal("0"),
                notas_especiales=hijo.notas_especiales,
                nombre_combo_padre=catalogo[combo_id]["nombre"],
                es_hijo_de=str(combo_id),
                es_hijo_combo=True,
                id_combo_padre=str(hijo.id_combo_padre),
            )
        )
    return normalizados


async def calcular_venta(
    conn: asyncpg.Connection,
    sucursal_id: UUID,
    detalles: Sequence[DetalleCreate],
) -> VentaCalculada:
    """Recalcula el pedido con el catálogo de `sucursal_id`.

    - 422 si el pedido está vacío, una cantidad está fuera de rango, un
      producto no existe o es de otra sucursal, no se vende en el POS, o los
      hijos de un combo no corresponden a su definición.
    - 409 si un producto está inactivo o si el precio/importe que mandó el
      cliente no coincide con el del catálogo.

    Devuelve los detalles con los precios del catálogo y el subtotal bruto.
    """
    if not detalles:
        raise PedidoInvalidoError("El pedido no tiene productos.")

    for detalle in detalles:
        _validar_cantidad(detalle)

    ids = list({_uuid_o_error(d.id, "producto") for d in detalles})
    catalogo = await producto_repository.obtener_para_venta(conn, ids)

    renglones: list[DetalleCreate] = []
    hijos: list[DetalleCreate] = []
    unidades_por_combo: dict[UUID, int] = {}
    for detalle in detalles:
        if detalle.es_hijo_combo:
            hijos.append(detalle)
            continue
        producto_id = UUID(detalle.id)
        producto = _producto_de_la_sucursal(catalogo, producto_id, sucursal_id)
        renglones.append(_normalizar_renglon(detalle, producto, producto_id))
        if producto["es_combo"]:
            unidades_por_combo[producto_id] = (
                unidades_por_combo.get(producto_id, 0) + detalle.cantidad
            )

    if not renglones:
        raise PedidoInvalidoError("El pedido no tiene productos.")

    hijos_normalizados: list[DetalleCreate] = []
    if hijos:
        definiciones = await producto_repository.obtener_definiciones_combo(
            conn, list(unidades_por_combo)
        )
        hijos_normalizados = _validar_hijos_combo(hijos, unidades_por_combo, definiciones, catalogo)

    # Mismo orden en que llegaron (cada combo seguido de sus hijos), que es el
    # que ven cocina y el ticket.
    iter_renglones = iter(renglones)
    iter_hijos = iter(hijos_normalizados)
    normalizados = [next(iter_hijos) if d.es_hijo_combo else next(iter_renglones) for d in detalles]
    subtotal = sum((r.subtotal for r in renglones), Decimal("0"))
    return VentaCalculada(detalles=normalizados, subtotal=subtotal)


def verificar_total(total_cliente: Decimal, total_servidor: Decimal) -> None:
    """409 si el total que mandó el cliente no es el que calculó el servidor."""
    if a_centavos(total_cliente) != a_centavos(total_servidor):
        raise PrecioCambiadoError(
            f"El total del pedido es {formatear_pesos(total_servidor)}, no "
            f"{formatear_pesos(total_cliente)}. Actualiza el pedido.",
            code="TOTAL_NO_COINCIDE",
        )
