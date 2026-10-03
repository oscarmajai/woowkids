"""Pendiente B9 B.4 / M6 / M7 / B23: lo que GET /turnos-caja/activo expone
del turno del cajero.

- M6: total_vendido es lo aplicado (lo cobrado menos el cambio entregado,
  como el esperado del arqueo), no el efectivo recibido; numero_ventas
  cuenta tickets (ver contar_ventas_apertura), no pagos.
- M7: efectivo_esperado en vivo y lo cobrado por método (efectivo neto del
  cambio), para el hub del turno.
- B23: con el conteo ya enviado, el turno trae el conteo guardado."""

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.services import turnos_caja_service as svc

SVC = "app.services.turnos_caja_service"


def _apertura(**extra: Any) -> dict[str, Any]:
    base = {
        "id": uuid4(),
        "sucursal_id": uuid4(),
        "sucursal_nombre": "Sucursal X",
        "cajero_id": uuid4(),
        "cajero_nombre": "Cajero X",
        "terminal": "CAJA 01",
        "caja_nombre": "Caja Patria 1",
        "fondo_inicial": Decimal("500"),
        "fecha_apertura": "2026-01-01T09:00:00",
        "estado": "ABIERTA",
        "monto_declarado": None,
        "conteo_json": None,
        "token_admin_jti": None,
        "observaciones_apertura": "Fondo con monedas de $10",
    }
    base.update(extra)
    return base


def _patches(activa: dict[str, Any], **sobrescribir: Any) -> list[Any]:
    valores: dict[str, Any] = {
        "get_apertura_activa_por_usuario": activa,
        # Recibido: 1,000 en efectivo + 300 en tarjeta; se dieron 120 de cambio.
        "sumar_total_ventas_apertura": Decimal("1300"),
        "contar_ventas_apertura": 3,
        "sumar_retiros_por_apertura": Decimal("200"),
        "sumar_ingresos_por_apertura": Decimal("50"),
        "sumar_cambio_apertura": Decimal("120"),
        "sumar_ventas_efectivo_apertura": Decimal("1000"),
        "sumar_devoluciones_efectivo_apertura": Decimal("0"),
        "obtener_movimientos_por_metodo": [
            {"metodo_nombre": "Efectivo", "metodo_tipo": "E", "total_ventas": Decimal("1000")},
            {"metodo_nombre": "Tarjeta", "metodo_tipo": "T", "total_ventas": Decimal("300")},
        ],
    }
    valores.update(sobrescribir)
    # Misma fórmula que caja_repository.calcular_efectivo_disponible.
    valores["calcular_efectivo_disponible"] = (
        Decimal(str(activa["fondo_inicial"]))
        + valores["sumar_ventas_efectivo_apertura"]
        + valores["sumar_ingresos_por_apertura"]
        - valores["sumar_retiros_por_apertura"]
        - valores["sumar_cambio_apertura"]
        - valores["sumar_devoluciones_efectivo_apertura"]
    )
    return [patch(f"{SVC}.{k}", AsyncMock(return_value=v)) for k, v in valores.items()]


async def _turno(activa: dict[str, Any], **sobrescribir: Any) -> Any:
    patches = _patches(activa, **sobrescribir)
    for p in patches:
        p.start()
    try:
        return await svc.obtener_turno_activo(object(), str(activa["cajero_id"]))  # type: ignore[arg-type]
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_total_vendido_es_neto_del_cambio_y_cuenta_tickets() -> None:
    resultado = await _turno(_apertura())

    assert resultado.numero_ventas == 3
    # M6: antes total_vendido = 1,300 (incluía los 120 devueltos de cambio).
    assert resultado.total_vendido == Decimal("1180")
    assert resultado.total_cambio == Decimal("120")
    # El bruto se conserva por compatibilidad.
    assert resultado.total_ventas == Decimal("1300")
    # Conteo a ciegas del cierre: nada de balance ni admin_email mientras el
    # turno sigue abierto.
    assert resultado.balance_por_metodo == []
    assert resultado.admin_email is None


@pytest.mark.asyncio
async def test_efectivo_esperado_y_ventas_por_metodo() -> None:
    resultado = await _turno(_apertura())

    # 500 fondo + 1,000 efectivo + 50 ingreso - 200 retiro - 120 cambio.
    assert resultado.efectivo_esperado == Decimal("1230")
    por_metodo = {v.metodo: v.total for v in resultado.ventas_por_metodo}
    assert por_metodo == {"efectivo": Decimal("880"), "tarjeta": Decimal("300")}
    assert sum(por_metodo.values()) == resultado.total_vendido


@pytest.mark.asyncio
async def test_efectivo_esperado_negativo_se_reporta_tal_cual() -> None:
    resultado = await _turno(
        _apertura(fondo_inicial=Decimal("2000")),
        sumar_retiros_por_apertura=Decimal("12000"),
        sumar_ventas_efectivo_apertura=Decimal("8315"),
        sumar_cambio_apertura=Decimal("0"),
        sumar_ingresos_por_apertura=Decimal("0"),
    )
    assert resultado.efectivo_esperado == Decimal("-1685")


@pytest.mark.asyncio
async def test_expone_nombre_de_caja_y_notas_de_apertura() -> None:
    resultado = await _turno(_apertura())
    assert resultado.terminal == "CAJA 01"
    assert resultado.caja_nombre == "Caja Patria 1"
    assert resultado.observaciones_apertura == "Fondo con monedas de $10"


@pytest.mark.asyncio
async def test_sin_conteo_enviado_no_hay_conteo_guardado() -> None:
    resultado = await _turno(_apertura())
    assert resultado.conteo_guardado is None


@pytest.mark.asyncio
async def test_conteo_en_espera_trae_el_conteo_guardado() -> None:
    conteo = {
        "desglose_efectivo": {
            "billetes": [{"denominacion": "500", "cantidad": 7}],
            "monedas": [{"denominacion": "10", "cantidad": 3}],
            "total": "3530",
        },
        "metodos_pago": [{"metodo": "Tarjeta", "monto": "5903"}],
    }
    resultado = await _turno(
        _apertura(
            estado="EN_CORTE",
            monto_declarado=Decimal("9433"),
            conteo_json=json.dumps(conteo),
        )
    )

    assert resultado.estado == "ESPERANDO_REVISION"
    assert resultado.conteo_guardado is not None
    assert resultado.conteo_guardado.total_declarado == Decimal("9433")
    assert resultado.conteo_guardado.desglose_efectivo["total"] == "3530"
    assert resultado.conteo_guardado.metodos_pago == [{"metodo": "Tarjeta", "monto": "5903"}]
