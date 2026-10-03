"""
app/services/devolucion_service.py
A4: devolución al cliente al cancelar una comanda ya cobrada.

Antes, cancelar una orden pagada no movía la caja (el efectivo esperado del
arqueo seguía contando la venta) y el cajero lo hacía sin autorización. Ahora:
  - Exige el token de PIN de un administrador de la sucursal de la comanda,
    el mismo que emite POST /turnos-caja/validar-pin-admin para el cierre,
    emitido para el turno abierto de quien cancela.
  - Registra la devolución en ese turno (devoluciones_comanda): la parte en
    efectivo (cobrado menos el cambio ya entregado) resta del efectivo
    esperado; los pagos con otros métodos quedan registrados como devueltos
    sin mover el efectivo.
  - Sin turno abierto, o si la venta se cobró en un turno ya cerrado, 409.
Una comanda sin pagos se cancela como siempre (no pasa por aquí).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import asyncpg

from app.exceptions.comandas import (
    AdminNoAutorizadoError,
    TurnoNoAbiertoParaDevolucionError,
    VentaDeTurnoCerradoError,
)
from app.repositories import devolucion_repository
from app.repositories.caja_repository import (
    bloquear_apertura,
    calcular_efectivo_disponible,
    get_apertura_activa_por_usuario,
)
from app.services import turnos_caja_service
from app.services.turnos_caja_service import EfectivoInsuficienteError


@dataclass
class PlanDevolucion:
    """Lo que hay que devolver de una comanda cobrada y en qué turno."""

    apertura_cancelador_id: str
    movimientos: list[dict[str, Any]] = field(default_factory=list)
    # Lo llena bloquear_turnos, ya con el turno bloqueado.
    fondo_inicial_cancelador: Decimal = Decimal("0")

    @property
    def aperturas_venta(self) -> list[str]:
        return sorted({str(m["apertura_caja_id"]) for m in self.movimientos})

    @property
    def efectivo(self) -> Decimal:
        """Efectivo que salió del cajón: cobros en efectivo (o sin método, la
        venta de POST /comandas) menos el cambio que ya se entregó."""
        cobrado = sum(
            (
                Decimal(str(m["monto"]))
                for m in self.movimientos
                if m["tipo_movimiento"] == "O" and m["es_efectivo"]
            ),
            Decimal("0"),
        )
        cambio = sum(
            (Decimal(str(m["monto"])) for m in self.movimientos if m["tipo_movimiento"] == "C"),
            Decimal("0"),
        )
        return cobrado - cambio

    @property
    def otros_metodos(self) -> list[dict[str, Any]]:
        return [m for m in self.movimientos if m["tipo_movimiento"] == "O" and not m["es_efectivo"]]


async def comanda_tiene_pagos(conn: asyncpg.Connection, comanda_id: str) -> bool:
    """Cobros en caja o pagos registrados para la comanda."""
    return bool(
        await devolucion_repository.movimientos_venta(conn, comanda_id)
    ) or await devolucion_repository.tiene_pagos_orden(conn, comanda_id)


async def planear(
    conn: asyncpg.Connection, comanda_id: str, usuario_id: str
) -> PlanDevolucion | None:
    """None si la comanda no tiene pagos (se cancela sin devolución). Si los
    tiene, valida que quien cancela tenga un turno operando y que la venta no
    sea de un turno ya cerrado. Los cobros se registran junto con la comanda y
    no cambian después, así que se pueden leer antes de los bloqueos."""
    movimientos = await devolucion_repository.movimientos_venta(conn, comanda_id)
    if not movimientos and not await devolucion_repository.tiene_pagos_orden(conn, comanda_id):
        return None

    apertura = await get_apertura_activa_por_usuario(conn, usuario_id)
    if not apertura or apertura["estado"] != "ABIERTA":
        raise TurnoNoAbiertoParaDevolucionError()
    if any(m["apertura_estado"] == "CERRADA" for m in movimientos):
        raise VentaDeTurnoCerradoError()
    return PlanDevolucion(apertura_cancelador_id=str(apertura["id"]), movimientos=movimientos)


async def bloquear_turnos(conn: asyncpg.Connection, plan: PlanDevolucion) -> None:
    """Bloquea (en orden de id, para no cruzarse con otra cancelación) el turno
    de quien cancela y los de la venta, y vuelve a validar sus estados: un
    cierre o un conteo que llegue en medio espera o hace fallar la
    cancelación. Va antes de bloquear la comanda (orden de bloqueo de caja:
    apertura_caja siempre primero). Debe correr dentro de una transacción."""
    for apertura_id in sorted({plan.apertura_cancelador_id, *plan.aperturas_venta}):
        apertura = await bloquear_apertura(conn, apertura_id)
        if apertura_id == plan.apertura_cancelador_id:
            if not apertura or apertura["estado"] != "ABIERTA":
                raise TurnoNoAbiertoParaDevolucionError()
            plan.fondo_inicial_cancelador = Decimal(str(apertura["fondo_inicial"]))
        if apertura and apertura["estado"] == "CERRADA":
            raise VentaDeTurnoCerradoError()


async def registrar(
    conn: asyncpg.Connection,
    plan: PlanDevolucion,
    *,
    comanda_id: str,
    sucursal_id: str,
    token_pin_admin: str,
    usuario_id: str,
) -> None:
    """Consume el token de PIN del administrador y registra la devolución.
    Debe correr dentro de la transacción de la cancelación, después de
    bloquear_turnos: si algo falla, el token no queda consumido."""
    admin_id = await turnos_caja_service.consumir_token_pin_admin(
        conn, token_pin_admin, plan.apertura_cancelador_id
    )
    if not await devolucion_repository.es_admin_de_sucursal(conn, admin_id, sucursal_id):
        raise AdminNoAutorizadoError()

    apertura_venta_id = plan.aperturas_venta[0] if plan.aperturas_venta else None
    efectivo = plan.efectivo
    if efectivo > 0:
        disponible = await calcular_efectivo_disponible(
            conn, plan.apertura_cancelador_id, plan.fondo_inicial_cancelador
        )
        # Igual que un retiro: no se puede sacar del cajón más de lo que hay.
        if efectivo > disponible:
            raise EfectivoInsuficienteError(disponible)
        metodo_efectivo = next(
            (
                str(m["metodo_pago_id"])
                for m in plan.movimientos
                if m["tipo_movimiento"] == "O" and m["es_efectivo"] and m["metodo_pago_id"]
            ),
            None,
        )
        await devolucion_repository.registrar(
            conn,
            comanda_id=comanda_id,
            apertura_caja_id=plan.apertura_cancelador_id,
            apertura_venta_id=apertura_venta_id,
            metodo_pago_id=metodo_efectivo,
            es_efectivo=True,
            monto=efectivo,
            autorizado_por=admin_id,
            creado_por=usuario_id,
        )

    for movimiento in plan.otros_metodos:
        await devolucion_repository.registrar(
            conn,
            comanda_id=comanda_id,
            apertura_caja_id=plan.apertura_cancelador_id,
            apertura_venta_id=str(movimiento["apertura_caja_id"]),
            metodo_pago_id=str(movimiento["metodo_pago_id"]),
            es_efectivo=False,
            monto=Decimal(str(movimiento["monto"])),
            autorizado_por=admin_id,
            creado_por=usuario_id,
        )
