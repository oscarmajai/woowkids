"""Máquina de estados de la reservación (A8) y reglas del PATCH (N12).

E2E: R-0008 estaba cancelada y se "cerró" como completada a las 01:51 para un
evento de las 16:00, y el cierre borró la nota de cancelación. El PATCH además
aceptaba cualquier `estado` y editaba fuera de plazo. Sin BD: repositories
simulados; el SQL real se prueba en tests/db/test_reservacion_estados_pg.py."""

from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.repositories import paquetes_repository, reservaciones_repository
from app.schemas.reservaciones import ReservacionesUpdate
from app.services import reservacion_estados, reservaciones
from fastapi import HTTPException

HOY = date(2026, 10, 3)
EVENTO_HOY_16 = (HOY, time(16, 0))


def _validar(actual: str, nuevo: str, ahora: datetime, **kw: Any) -> None:
    datos: dict[str, Any] = {
        "fecha_evento": EVENTO_HOY_16[0],
        "hora_inicio": EVENTO_HOY_16[1],
        "ahora_local": ahora,
        "saldo_pendiente": Decimal(0),
        "monto_pagado": Decimal("7615"),
        "anticipo_minimo": Decimal("2285"),
    }
    datos.update(kw)
    reservacion_estados.validar_transicion(actual, nuevo, **datos)


DESPUES = datetime(2026, 10, 3, 16, 30)
ANTES = datetime(2026, 10, 3, 1, 51)


@pytest.mark.parametrize("terminal", ["cancelada", "completada"])
@pytest.mark.parametrize("destino", ["pendiente", "confirmada", "en_curso", "completada"])
def test_nada_sale_de_un_estado_terminal(terminal: str, destino: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _validar(terminal, destino, DESPUES)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "RESERVACION_CERRADA"


def test_cancelada_a_completada_se_rechaza_con_mensaje_claro() -> None:
    with pytest.raises(HTTPException) as exc:
        _validar("cancelada", "completada", DESPUES)
    assert "cancelada" in exc.value.detail["message"]


def test_completar_antes_de_que_empiece_el_evento_se_rechaza() -> None:
    with pytest.raises(HTTPException) as exc:
        _validar("confirmada", "completada", ANTES)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "EVENTO_NO_INICIADO"
    assert "03/10/2026 a las 16:00" in exc.value.detail["message"]


def test_completar_con_saldo_se_rechaza() -> None:
    with pytest.raises(HTTPException) as exc:
        _validar("confirmada", "completada", DESPUES, saldo_pendiente=Decimal("5330"))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "SALDO_PENDIENTE"
    assert "$5,330.00" in exc.value.detail["message"]


@pytest.mark.parametrize("desde", ["pendiente", "confirmada", "en_curso"])
def test_completar_un_evento_iniciado_y_liquidado_procede(desde: str) -> None:
    _validar(desde, "completada", DESPUES)


def test_no_se_regresa_a_pendiente() -> None:
    with pytest.raises(HTTPException) as exc:
        _validar("confirmada", "pendiente", DESPUES)
    assert exc.value.detail["code"] == "TRANSICION_INVALIDA"


def test_confirmar_exige_el_anticipo_minimo() -> None:
    with pytest.raises(HTTPException) as exc:
        _validar("pendiente", "confirmada", ANTES, monto_pagado=Decimal("1000"))
    assert exc.value.detail["code"] == "ANTICIPO_INSUFICIENTE"
    _validar("pendiente", "confirmada", ANTES, monto_pagado=Decimal("2285"))


def test_cancelar_procede_desde_pendiente_y_confirmada() -> None:
    _validar("pendiente", "cancelada", ANTES)
    _validar("confirmada", "cancelada", ANTES)


def test_anexar_nota_conserva_las_existentes() -> None:
    previa = "Cancelada automáticamente: no se liquidó una semana antes del evento."
    assert reservacion_estados.anexar_nota(previa, "Todo bien", "Cierre") == (
        f"{previa}\nCierre: Todo bien"
    )
    assert reservacion_estados.anexar_nota(previa, "  ", "Cierre") == previa
    assert reservacion_estados.anexar_nota(None, "Todo bien", "Cierre") == "Cierre: Todo bien"


# ── Service: PATCH y cierre ──────────────────────────────────────────────────


def _conn() -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def transaccion() -> Any:
        yield

    conn.transaction = transaccion
    return conn


def _fila(**cambios: Any) -> dict[str, Any]:
    datos: dict[str, Any] = {
        "id": uuid4(),
        "sucursal_id": uuid4(),
        "paquete_id": uuid4(),
        "activo": True,
        "estado": "confirmada",
        "fecha_evento": HOY,
        "hora_inicio": time(16, 0),
        "hora_fin": time(19, 0),
        "numero_personas": 12,
        "precio_total": Decimal("7615.00"),
        "monto_pagado": Decimal("7615.00"),
        "saldo_pendiente": Decimal("0.00"),
        "notas": None,
    }
    datos.update(cambios)
    return datos


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    estado: dict[str, Any] = {"fila": _fila(), "ahora": DESPUES}
    monkeypatch.setattr(
        reservaciones_repository,
        "obtener_para_actualizar",
        AsyncMock(side_effect=lambda conn, rid: estado["fila"]),
    )
    monkeypatch.setattr(
        reservaciones_repository,
        "ahora_en_sucursal",
        AsyncMock(side_effect=lambda conn, sid: estado["ahora"]),
    )
    monkeypatch.setattr(reservaciones_repository, "hoy_en_sucursal", AsyncMock(return_value=HOY))
    monkeypatch.setattr(
        paquetes_repository, "obtener", AsyncMock(return_value={"anticipo_porcentaje": 30})
    )
    actualizar = AsyncMock(return_value=None)
    monkeypatch.setattr(reservaciones_repository, "actualizar", actualizar)
    estado["actualizar"] = actualizar
    return estado


async def test_patch_no_cierra_una_reservacion_cancelada(repo: dict[str, Any]) -> None:
    repo["fila"] = _fila(estado="cancelada", notas="Cancelada automáticamente")
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(_conn(), uuid4(), ReservacionesUpdate(estado="completada"))
    assert exc.value.status_code == 409
    repo["actualizar"].assert_not_awaited()


async def test_patch_no_edita_una_reservacion_completada(repo: dict[str, Any]) -> None:
    repo["fila"] = _fila(estado="completada")
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(_conn(), uuid4(), ReservacionesUpdate(notas="x"))
    assert exc.value.status_code == 409
    repo["actualizar"].assert_not_awaited()


async def test_patch_completar_antes_del_evento_responde_409(repo: dict[str, Any]) -> None:
    repo["ahora"] = ANTES
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(_conn(), uuid4(), ReservacionesUpdate(estado="completada"))
    assert exc.value.detail["code"] == "EVENTO_NO_INICIADO"
    repo["actualizar"].assert_not_awaited()


async def test_patch_fuera_de_plazo_no_cambia_invitados(repo: dict[str, Any]) -> None:
    repo["fila"] = _fila(fecha_evento=HOY + timedelta(days=7))
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(_conn(), uuid4(), ReservacionesUpdate(numero_personas=15))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "FUERA_DE_PLAZO"
    assert "02/10/2026" in exc.value.detail["message"]
    repo["actualizar"].assert_not_awaited()


async def test_patch_no_mueve_la_fecha_dentro_de_la_semana_del_evento(
    repo: dict[str, Any],
) -> None:
    repo["fila"] = _fila(fecha_evento=HOY + timedelta(days=30))
    body = ReservacionesUpdate(fecha_evento=HOY + timedelta(days=3))
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(_conn(), uuid4(), body)
    assert exc.value.detail["code"] == "FUERA_DE_PLAZO"


async def test_patch_fuera_de_plazo_si_corrige_contacto_y_notas(repo: dict[str, Any]) -> None:
    repo["fila"] = _fila(fecha_evento=HOY + timedelta(days=2))
    body = ReservacionesUpdate(telefono_cliente="3312345678", notas="Llega 15 min antes")
    with pytest.raises(HTTPException):  # actualizar() simulado devuelve None -> 404
        await reservaciones.actualizar(_conn(), uuid4(), body)
    assert repo["actualizar"].await_args.args[2] == {
        "telefono_cliente": "3312345678",
        "notas": "Llega 15 min antes",
    }


async def test_patch_con_el_mismo_estado_no_es_transicion(repo: dict[str, Any]) -> None:
    repo["ahora"] = ANTES
    body = ReservacionesUpdate(estado="confirmada", notas="x")
    with pytest.raises(HTTPException):  # 404 del actualizar() simulado
        await reservaciones.actualizar(_conn(), uuid4(), body)
    assert repo["actualizar"].await_args.args[2] == {"notas": "x"}


async def test_cerrar_agrega_la_nota_sin_borrar_las_anteriores(repo: dict[str, Any]) -> None:
    repo["fila"] = _fila(notas="Pidió pastel sin nuez")
    usuario = uuid4()
    with pytest.raises(HTTPException):  # 404 del actualizar() simulado
        await reservaciones.cerrar(_conn(), uuid4(), "Sin incidencias", usuario)
    assert repo["actualizar"].await_args.args[2] == {
        "estado": "completada",
        "notas": "Pidió pastel sin nuez\nCierre del evento: Sin incidencias",
        "modificado_por": usuario,
    }


async def test_cerrar_con_saldo_responde_409(repo: dict[str, Any]) -> None:
    repo["fila"] = _fila(monto_pagado=Decimal("2285"), saldo_pendiente=Decimal("5330"))
    with pytest.raises(HTTPException) as exc:
        await reservaciones.cerrar(_conn(), uuid4(), None, uuid4())
    assert exc.value.detail["code"] == "SALDO_PENDIENTE"
    repo["actualizar"].assert_not_awaited()
