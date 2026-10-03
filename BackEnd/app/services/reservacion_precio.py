"""Precio y reglas de cobro de una reservación, calculados en el servidor (C2).

El backend es la fuente de verdad del precio: el navegador manda lo que cree
que cuesta el evento solo para detectar que su pantalla quedó vieja (si no
coincide, 409 y se recarga). Las reglas replican exactamente lo que hoy cobra
el asistente de alta (`FrontEnd/src/pages/NuevaReservacionPage.vue`,
`utils/horario.ts::horasFacturables` y `utils/reservacionPrecio.ts`):

    total = precio_base del paquete
          + niños x precio_hora_pulsera x horas facturables   (pulseras)
          + Σ precio de cada extra (cantidad 1, ver M15)
          + Σ precio_unitario x cantidad de cada producto adicional

Funciones puras (sin BD) para poder probarlas sin mocks.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException, status

CENTAVO = Decimal("0.01")

# Piso de anticipo del negocio; un paquete puede pedir más (`anticipo_porcentaje`).
PORCENTAJE_ANTICIPO_MINIMO = Decimal("30")

# Un evento debe quedar liquidado esta cantidad de días antes (lo hace cumplir el
# scheduler de reservaciones vencidas). Al reservar con este plazo o menos ya no
# hay tiempo de "liquidar después": se exige el 100 % en el alta.
DIAS_LIMITE_LIQUIDACION = 7


def _dinero(valor: Decimal | int | str) -> Decimal:
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def formato_mxn(valor: Decimal) -> str:
    """$13,815.00 — mismo formato que muestra el frontend."""
    return f"${_dinero(valor):,.2f}"


def horas_facturables(hora_inicio: time, hora_fin: time) -> int:
    """Toda fracción de hora se cobra completa, con mínimo 1 hora.

    Igual que `horasFacturables()` del frontend: solo cuenta horas y minutos
    (no segundos) y, si el fin es anterior al inicio, asume que cruza la
    medianoche.
    """
    minutos = (hora_fin.hour * 60 + hora_fin.minute) - (hora_inicio.hour * 60 + hora_inicio.minute)
    if minutos < 0:
        minutos += 24 * 60
    return max(1, math.ceil(minutos / 60))


def calcular_pulseras(precio_hora_pulsera: Decimal, invitados: int, horas: int) -> Decimal:
    """Cargo de pulseras: tarifa por hora x invitados x horas (mínimo 1 hora)."""
    return _dinero(Decimal(precio_hora_pulsera) * invitados * max(1, horas))


@dataclass(frozen=True)
class DesglosePrecio:
    precio_base: Decimal
    # Se guarda en `precio_personas_extra` por compatibilidad: hoy es el cargo
    # de pulseras (B22).
    precio_pulseras: Decimal
    precio_extras: Decimal
    precio_productos: Decimal
    horas_reservadas: int

    @property
    def precio_total(self) -> Decimal:
        return _dinero(
            self.precio_base + self.precio_pulseras + self.precio_extras + self.precio_productos
        )


def calcular_desglose(
    paquete: dict[str, Any],
    numero_personas: int,
    hora_inicio: time,
    hora_fin: time,
    precios_extras: Iterable[Decimal],
    productos: Iterable[tuple[Decimal, int]],
) -> DesglosePrecio:
    """Precio de una reservación nueva con los precios de catálogo.

    `precios_extras`: precio de catálogo de cada extra elegido (cada uno se
    cobra una sola vez, como hoy el asistente; pendiente M15).
    `productos`: pares (precio_unitario de catálogo, cantidad).
    """
    horas = horas_facturables(hora_inicio, hora_fin)
    return DesglosePrecio(
        precio_base=_dinero(paquete["precio_base"]),
        precio_pulseras=calcular_pulseras(
            paquete["precio_hora_pulsera"] or Decimal(0), numero_personas, horas
        ),
        precio_extras=_dinero(sum((Decimal(p) for p in precios_extras), Decimal(0))),
        precio_productos=_dinero(
            sum((Decimal(precio) * cantidad for precio, cantidad in productos), Decimal(0))
        ),
        horas_reservadas=horas,
    )


def recalcular_total_edicion(
    reservacion: dict[str, Any],
    precio_hora_pulsera: Decimal,
    numero_personas: int,
    horas_reservadas: int,
) -> tuple[Decimal, Decimal]:
    """(pulseras, total) de una reservación existente al cambiarle invitados u
    horas. Igual que `recalcularReservacion()` del frontend: se reconstruye
    desde las partes guardadas y `precio_horas` se conserva (histórico)."""
    pulseras = calcular_pulseras(precio_hora_pulsera, numero_personas, horas_reservadas)
    total = _dinero(
        Decimal(reservacion["precio_base"])
        + pulseras
        + Decimal(reservacion["precio_horas"])
        + Decimal(reservacion["precio_productos"])
        + Decimal(reservacion["precio_extras"])
        - Decimal(reservacion["descuento"])
    )
    return pulseras, total


def porcentaje_anticipo(anticipo_porcentaje_paquete: Decimal | None) -> Decimal:
    """Anticipo mínimo: el 30 % del negocio o el del paquete si es mayor (M16)."""
    if anticipo_porcentaje_paquete is None:
        return PORCENTAJE_ANTICIPO_MINIMO
    return max(PORCENTAJE_ANTICIPO_MINIMO, Decimal(anticipo_porcentaje_paquete))


def monto_por_porcentaje(total: Decimal, porcentaje: Decimal) -> Decimal:
    """Monto de un porcentaje del total redondeado a pesos completos (half-up),
    como los atajos de anticipo del asistente."""
    return (Decimal(total) * Decimal(porcentaje) / 100).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )


def exige_liquidacion(dias_para_evento: int) -> bool:
    """A 7 días o menos del evento se cobra el 100 % al reservar."""
    return dias_para_evento <= DIAS_LIMITE_LIQUIDACION


def _texto_dias(dias: int) -> str:
    if dias <= 0:
        return "es hoy"
    if dias == 1:
        return "es mañana"
    return f"es en {dias} días"


def verificar_precio_cliente(enviado: Decimal, calculado: Decimal) -> None:
    """409 si el total que vio el cliente no es el que cobra el servidor.

    No se corrige en silencio: el cajero le está cotizando al cliente, así que
    debe ver el precio real antes de cobrar."""
    if _dinero(enviado) != _dinero(calculado):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PRECIO_CAMBIADO",
                "message": (
                    f"El precio de la reservación cambió: {formato_mxn(calculado)}. "
                    "Actualiza la reservación."
                ),
                "precio_total": str(_dinero(calculado)),
            },
        )


def validar_cupo(paquete: dict[str, Any], numero_personas: int) -> None:
    minimo, maximo = paquete["min_invitados"], paquete["max_invitados"]
    if not minimo <= numero_personas <= maximo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "CUPO_PAQUETE",
                "message": (
                    f"El paquete «{paquete['nombre']}» es para {minimo} a {maximo} invitados "
                    f"(se capturaron {numero_personas})."
                ),
            },
        )


def validar_anticipo(
    total: Decimal,
    pagado: Decimal,
    porcentaje_minimo: Decimal,
    dias_para_evento: int,
) -> None:
    """Lo cobrado al reservar debe cubrir el anticipo mínimo, o el total si el
    evento es en 7 días o menos, y nunca rebasar el total."""
    total = _dinero(total)
    pagado = _dinero(pagado)
    if pagado > total:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "PAGO_EXCEDE_TOTAL",
                "message": (
                    f"El pago ({formato_mxn(pagado)}) rebasa el total de la reservación "
                    f"({formato_mxn(total)})."
                ),
            },
        )
    if exige_liquidacion(dias_para_evento):
        if pagado < total:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "LIQUIDACION_REQUERIDA",
                    "message": (
                        f"El evento {_texto_dias(dias_para_evento)}: se debe liquidar al "
                        f"reservar ({formato_mxn(total)})."
                    ),
                },
            )
        return
    # Redondeado a pesos, pero nunca más que el total (un total con centavos al 100 %).
    minimo = min(total, monto_por_porcentaje(total, porcentaje_minimo))
    if pagado < minimo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "ANTICIPO_INSUFICIENTE",
                "message": (
                    f"El anticipo mínimo es {porcentaje_minimo.normalize():f}% "
                    f"({formato_mxn(minimo)})."
                ),
            },
        )
