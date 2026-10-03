"""Reglas de precio y cobro de reservaciones calculadas en el servidor (C2/C3).

Los casos con números reales salen de las reservaciones de las pruebas E2E del
2026-10-03 (R-0008 y R-0009): el cálculo del servidor debe dar exactamente lo
que cobró el asistente de alta del frontend."""

from datetime import time
from decimal import Decimal

import pytest
from app.services import reservacion_precio as rp
from fastapi import HTTPException


def _paquete(**cambios: object) -> dict:
    base = {
        "nombre": "Básico",
        "precio_base": Decimal("3800.00"),
        "precio_hora_pulsera": Decimal("70.00"),
        "min_invitados": 10,
        "max_invitados": 20,
        "anticipo_porcentaje": None,
    }
    base.update(cambios)
    return base


@pytest.mark.parametrize(
    ("inicio", "fin", "horas"),
    [
        (time(16, 0), time(19, 0), 3),
        (time(16, 0), time(19, 1), 4),  # toda fracción se cobra completa
        (time(16, 0), time(16, 30), 1),
        (time(16, 0), time(16, 0), 1),  # mínimo 1 hora
        (time(22, 0), time(1, 0), 3),  # cruza medianoche, como el front
        (time(16, 0, 0), time(17, 0, 59), 1),  # los segundos no cuentan
    ],
)
def test_horas_facturables_igual_que_el_frontend(inicio: time, fin: time, horas: int) -> None:
    assert rp.horas_facturables(inicio, fin) == horas


def test_desglose_r0008_coincide_con_lo_que_cobro_el_asistente() -> None:
    # 12 niños, 16:00-19:00, pulsera $70/h, extras $450 + $35, productos $810.
    desglose = rp.calcular_desglose(
        _paquete(),
        12,
        time(16, 0),
        time(19, 0),
        [Decimal("450.00"), Decimal("35.00")],
        [(Decimal("135.00"), 6)],
    )
    assert desglose.precio_pulseras == Decimal("2520.00")
    assert desglose.precio_extras == Decimal("485.00")
    assert desglose.precio_productos == Decimal("810.00")
    assert desglose.horas_reservadas == 3
    assert desglose.precio_total == Decimal("7615.00")


def test_desglose_r0009_premium_cuatro_horas() -> None:
    desglose = rp.calcular_desglose(
        _paquete(precio_base=Decimal("6900.00"), precio_hora_pulsera=Decimal("60.00")),
        20,
        time(11, 0),
        time(15, 0),
        [Decimal("890.00"), Decimal("350.00")],
        [(Decimal("175.00"), 5)],
    )
    assert desglose.precio_pulseras == Decimal("4800.00")
    assert desglose.precio_total == Decimal("13815.00")


def test_recalcular_total_edicion_conserva_partes_historicas() -> None:
    reservacion = {
        "precio_base": Decimal("3800.00"),
        "precio_horas": Decimal("100.00"),
        "precio_productos": Decimal("810.00"),
        "precio_extras": Decimal("485.00"),
        "descuento": Decimal("50.00"),
    }
    pulseras, total = rp.recalcular_total_edicion(reservacion, Decimal("70.00"), 12, 4)
    assert pulseras == Decimal("3360.00")
    assert total == Decimal("8505.00")


def test_monto_por_porcentaje_redondea_a_pesos_como_el_front() -> None:
    # R-0008: 30 % de 7615 = 2284.5 -> 2285 (Math.round del asistente).
    assert rp.monto_por_porcentaje(Decimal("7615.00"), Decimal("30")) == Decimal("2285")
    assert rp.monto_por_porcentaje(Decimal("13815.00"), Decimal("40")) == Decimal("5526")


def test_porcentaje_anticipo_respeta_el_del_paquete_si_es_mayor() -> None:
    assert rp.porcentaje_anticipo(None) == Decimal("30")
    assert rp.porcentaje_anticipo(Decimal("40.00")) == Decimal("40.00")
    assert rp.porcentaje_anticipo(Decimal("20.00")) == Decimal("30")


def test_verificar_precio_cliente_rechaza_precio_manipulado() -> None:
    with pytest.raises(HTTPException) as exc:
        rp.verificar_precio_cliente(Decimal("1"), Decimal("13815.00"))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "PRECIO_CAMBIADO"
    assert exc.value.detail["message"] == (
        "El precio de la reservación cambió: $13,815.00. Actualiza la reservación."
    )


def test_verificar_precio_cliente_tolera_ruido_de_flotante() -> None:
    # El front suma en float: 7615.000000000001 es el mismo precio.
    rp.verificar_precio_cliente(Decimal("7615.000000000001"), Decimal("7615.00"))


def test_validar_cupo_rechaza_40_invitados_en_paquete_de_30() -> None:
    with pytest.raises(HTTPException) as exc:
        rp.validar_cupo(_paquete(min_invitados=10, max_invitados=30), 40)
    assert exc.value.status_code == 422
    rp.validar_cupo(_paquete(min_invitados=10, max_invitados=30), 30)


def test_anticipo_minimo_del_30() -> None:
    total = Decimal("7615.00")
    rp.validar_anticipo(total, Decimal("2285"), Decimal("30"), 30)
    with pytest.raises(HTTPException) as exc:
        rp.validar_anticipo(total, Decimal("2284"), Decimal("30"), 30)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "ANTICIPO_INSUFICIENTE"
    assert "30%" in exc.value.detail["message"]


def test_anticipo_cero_se_rechaza() -> None:
    with pytest.raises(HTTPException):
        rp.validar_anticipo(Decimal("7615.00"), Decimal("0"), Decimal("30"), 30)


def test_anticipo_del_paquete_premium_40() -> None:
    with pytest.raises(HTTPException) as exc:
        rp.validar_anticipo(Decimal("13815.00"), Decimal("4145"), Decimal("40"), 30)
    assert "40%" in exc.value.detail["message"]
    rp.validar_anticipo(Decimal("13815.00"), Decimal("5526"), Decimal("40"), 30)


@pytest.mark.parametrize("dias", [0, 1, 7])
def test_a_siete_dias_o_menos_se_exige_el_total(dias: int) -> None:
    total = Decimal("7615.00")
    with pytest.raises(HTTPException) as exc:
        rp.validar_anticipo(total, Decimal("5000"), Decimal("30"), dias)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "LIQUIDACION_REQUERIDA"
    assert "se debe liquidar al reservar" in exc.value.detail["message"]
    rp.validar_anticipo(total, total, Decimal("30"), dias)


def test_a_ocho_dias_basta_el_anticipo() -> None:
    rp.validar_anticipo(Decimal("7615.00"), Decimal("2285"), Decimal("30"), 8)


def test_pago_mayor_al_total_se_rechaza() -> None:
    with pytest.raises(HTTPException) as exc:
        rp.validar_anticipo(Decimal("1000.00"), Decimal("1000.01"), Decimal("30"), 30)
    assert exc.value.detail["code"] == "PAGO_EXCEDE_TOTAL"


def test_minimo_redondeado_nunca_pasa_del_total() -> None:
    # Paquete que pide el 100 % con un total con centavos: el mínimo es el total.
    rp.validar_anticipo(Decimal("7615.50"), Decimal("7615.50"), Decimal("100"), 30)
