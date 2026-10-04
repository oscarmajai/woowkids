"""A4: en el arqueo, cada devolución a un cliente baja el esperado de SU método
(no solo la de efectivo) y cada renglón la trae aparte para mostrarla.

Antes solo se restaba la de efectivo: cancelar una orden cobrada con tarjeta
dejaba el esperado de tarjeta inflado y un faltante falso al cerrar."""

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.services import turnos_caja_service as svc

SVC = "app.services.turnos_caja_service"
TARJETA = str(uuid4())
TRANSFERENCIA = str(uuid4())


def _apertura(metodos: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "fondo_inicial": Decimal("500"),
        "conteo_json": json.dumps({"desglose_efectivo": {"total": "800"}, "metodos_pago": metodos}),
    }


async def _balance(devoluciones: list[dict[str, Any]], metodos: list[dict[str, Any]]) -> Any:
    valores: dict[str, Any] = {
        "sumar_retiros_por_apertura": Decimal("0"),
        "sumar_cambio_apertura": Decimal("0"),
        "sumar_ingresos_por_apertura": Decimal("0"),
        "sumar_ventas_efectivo_apertura": Decimal("400"),
        # 400 en efectivo + 300 en tarjeta.
        "sumar_total_ventas_apertura": Decimal("700"),
        "sumar_devoluciones_por_metodo_apertura": devoluciones,
        "obtener_movimientos_por_metodo": [
            {
                "metodo_pago_id": uuid4(),
                "metodo_nombre": "Efectivo",
                "metodo_tipo": "E",
                "total_ventas": Decimal("400"),
            },
            {
                "metodo_pago_id": TARJETA,
                "metodo_nombre": "Tarjeta",
                "metodo_tipo": "T",
                "total_ventas": Decimal("300"),
            },
        ],
    }
    patches = [patch(f"{SVC}.{k}", AsyncMock(return_value=v)) for k, v in valores.items()]
    for p in patches:
        p.start()
    try:
        return await svc._calcular_balance(object(), _apertura(metodos), "turno")  # type: ignore[arg-type]
    finally:
        for p in patches:
            p.stop()


def _dev(
    es_efectivo: bool, total: str, metodo_id: str | None, nombre: str | None
) -> dict[str, Any]:
    return {
        "es_efectivo": es_efectivo,
        "metodo_pago_id": metodo_id,
        "metodo_nombre": nombre,
        "total": Decimal(total),
    }


async def test_sin_devoluciones_no_cambia_nada() -> None:
    esperado, declarado, diferencia, balance = await _balance(
        [], [{"metodo": "tarjeta", "monto": "300"}]
    )
    filas = {f.metodo: f for f in balance}
    assert filas["efectivo"].esperado == Decimal("900")
    assert filas["tarjeta"].esperado == Decimal("300")
    assert all(f.devoluciones == 0 for f in balance)
    assert esperado == Decimal("1200")
    assert diferencia == declarado - esperado


async def test_cada_devolucion_baja_el_esperado_de_su_metodo() -> None:
    esperado, _, _, balance = await _balance(
        [_dev(True, "50", None, None), _dev(False, "120", TARJETA, "Tarjeta")],
        [{"metodo": "tarjeta", "monto": "180"}],
    )
    filas = {f.metodo: f for f in balance}
    assert (filas["efectivo"].esperado, filas["efectivo"].devoluciones) == (
        Decimal("850"),
        Decimal("50"),
    )
    # 300 cobrados - 120 devueltos: el cajero declaró 180 y cuadra.
    assert (filas["tarjeta"].esperado, filas["tarjeta"].devoluciones) == (
        Decimal("180"),
        Decimal("120"),
    )
    assert filas["tarjeta"].diferencia == Decimal("0")
    # El total general resta todas las devoluciones, no solo el efectivo.
    assert esperado == Decimal("1200") - Decimal("170")


async def test_devolucion_de_un_metodo_sin_cobros_en_el_turno() -> None:
    """La venta se cobró en otro turno: el renglón aparece con el esperado en
    negativo por lo devuelto (la terminal del turno mostrará el reembolso)."""
    _, _, _, balance = await _balance(
        [_dev(False, "90", TRANSFERENCIA, "Transferencia")],
        [{"metodo": "transferencia", "monto": "0"}],
    )
    filas = {f.metodo: f for f in balance}
    assert filas["transferencia"].label == "Transferencia"
    assert filas["transferencia"].esperado == Decimal("-90")
    assert filas["transferencia"].devoluciones == Decimal("90")
    assert filas["transferencia"].diferencia == Decimal("90")
    # Y no se duplica como "declarado sin registrar".
    assert [f.metodo for f in balance].count("transferencia") == 1
