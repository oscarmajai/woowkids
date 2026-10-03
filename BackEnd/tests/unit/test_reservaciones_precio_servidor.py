"""El alta y la edición de reservaciones usan el precio del servidor (C2) y la
regla de liquidación a 7 días (C3). Sin BD: repositories simulados.

Reproduce el ataque de las pruebas E2E (R-0011): Paquete Premium de máximo 30
invitados con 40, `precio_total: 1`, `anticipo: 0`, `estado: confirmada`."""

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.models.producto import Producto
from app.repositories import (
    extras_repository,
    paquetes_repository,
    producto_repository,
    reservacion_extras_repository,
    reservacion_productos_repository,
    reservaciones_repository,
)
from app.schemas.pagos_reservacion import (
    PagoReservacionItem,
    PagosReservacionCompletarResponse,
)
from app.schemas.reservaciones import ReservacionesCrear, ReservacionesUpdate
from app.schemas.reservaciones_completa import (
    ReservacionCompletaExtraItem,
    ReservacionCompletaProductoItem,
    ReservacionCompletaRequest,
)
from app.services import pagos_reservacion, reservaciones
from fastapi import HTTPException

SUCURSAL_ID = uuid4()
OTRA_SUCURSAL_ID = uuid4()
PAQUETE_ID = uuid4()
EXTRA_ID = uuid4()
PRODUCTO_ID = uuid4()
HOY = date(2026, 10, 3)


def _conn() -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def transaccion() -> Any:
        yield

    conn.transaction = transaccion
    return conn


PAQUETE_PREMIUM = {
    "id": PAQUETE_ID,
    "sucursal_id": SUCURSAL_ID,
    "nombre": "Premium",
    "activo": True,
    "min_invitados": 10,
    "max_invitados": 30,
    "precio_base": Decimal("6900.00"),
    "precio_hora_pulsera": Decimal("60.00"),
    "anticipo_porcentaje": Decimal("40.00"),
}

EXTRA_ANIMADOR = {
    "id": EXTRA_ID,
    "sucursal_id": SUCURSAL_ID,
    "nombre": "Animador adicional",
    "precio": Decimal("350.00"),
    "activo": True,
}


def _producto(**cambios: Any) -> Producto:
    datos: dict[str, Any] = {
        "id": str(PRODUCTO_ID),
        "nombre": "Pizza familiar",
        "precio_unitario": Decimal("175.00"),
        "tipo": "A",
        "sucursal_id": str(SUCURSAL_ID),
        "activo": True,
    }
    datos.update(cambios)
    return Producto(**datos)


# Premium, 20 niños, 11:00-15:00 (4 h): 6900 + 20*60*4 + 350 + 2*175 = 12400
TOTAL_CORRECTO = Decimal("12400.00")


def _reservacion(**cambios: Any) -> ReservacionesCrear:
    datos: dict[str, Any] = {
        "sucursal_id": SUCURSAL_ID,
        "tipo_evento_id": uuid4(),
        "paquete_id": PAQUETE_ID,
        "nombre_cliente": "Cliente QA",
        "telefono_cliente": "3312345678",
        "fecha_evento": HOY + timedelta(days=30),
        "hora_inicio": time(11, 0),
        "hora_fin": time(15, 0),
        "numero_personas": 20,
        "precio_base": Decimal("6900.00"),
        "precio_total": TOTAL_CORRECTO,
        "anticipo": Decimal("0"),
        "estado": "pendiente",
    }
    datos.update(cambios)
    return ReservacionesCrear(**datos)


def _request(
    pagado: Decimal = Decimal("4960"),
    cambio: Decimal = Decimal("0"),
    **cambios: Any,
) -> ReservacionCompletaRequest:
    return ReservacionCompletaRequest(
        reservacion=_reservacion(**cambios),
        extras=[ReservacionCompletaExtraItem(extra_id=EXTRA_ID, cantidad=1, precio_unitario=1)],
        productos=[
            ReservacionCompletaProductoItem(producto_id=PRODUCTO_ID, cantidad=2, precio_unitario=1)
        ],
        pagos=[PagoReservacionItem(metodo_pago_id=uuid4(), monto=pagado + cambio)],
        cambio=cambio,
    )


@pytest.fixture
def repos(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Catálogo y BD simulados. Devuelve los mocks de escritura para revisar
    qué se guardó."""
    guardado: dict[str, Any] = {}

    async def fake_crear(conn: Any, data: dict[str, Any]) -> dict[str, Any]:
        guardado.update(data)
        return _fila(data)

    async def fake_obtener(conn: Any, reservacion_id: UUID) -> dict[str, Any]:
        return _fila(guardado)

    monkeypatch.setattr(paquetes_repository, "obtener", AsyncMock(return_value=PAQUETE_PREMIUM))
    monkeypatch.setattr(extras_repository, "obtener", AsyncMock(return_value=EXTRA_ANIMADOR))
    monkeypatch.setattr(producto_repository, "obtener", AsyncMock(return_value=_producto()))
    monkeypatch.setattr(reservaciones_repository, "hoy_en_sucursal", AsyncMock(return_value=HOY))
    monkeypatch.setattr(
        reservaciones_repository, "siguiente_folio", AsyncMock(return_value="R-0100")
    )
    monkeypatch.setattr(reservaciones_repository, "crear", fake_crear)
    monkeypatch.setattr(reservaciones_repository, "obtener", fake_obtener)

    crear_extra = AsyncMock(side_effect=lambda conn, **kw: _fila_item(kw, "extra_id"))
    crear_producto = AsyncMock(side_effect=lambda conn, **kw: _fila_item(kw, "producto_id"))
    monkeypatch.setattr(reservacion_extras_repository, "crear", crear_extra)
    monkeypatch.setattr(reservacion_productos_repository, "crear", crear_producto)
    completar = AsyncMock(
        return_value=PagosReservacionCompletarResponse(pagos=[], cambio=Decimal("0"))
    )
    monkeypatch.setattr(pagos_reservacion, "completar", completar)
    return {
        "reservacion": guardado,
        "crear_extra": crear_extra,
        "crear_producto": crear_producto,
        "completar": completar,
    }


def _fila(data: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        "id": uuid4(),
        "monto_pagado": data.get("anticipo", Decimal(0)),
        "saldo_pendiente": data["precio_total"] - data.get("anticipo", Decimal(0)),
        "comanda_enviada": False,
        "activo": True,
        "creado": datetime.now(UTC),
        "creado_por": None,
        "modificado": None,
        "modificado_por": None,
    }


def _fila_item(kw: dict[str, Any], llave: str) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "reservacion_id": kw["reservacion_id"],
        llave: kw[llave],
        "cantidad": kw["cantidad"],
        "precio_unitario": kw["precio_unitario"],
        "subtotal": kw["precio_unitario"] * kw["cantidad"],
        "notas": kw.get("notas"),
        "creado": datetime.now(UTC),
        "creado_por": None,
    }


async def _crear_completa(body: ReservacionCompletaRequest) -> Any:
    return await reservaciones.crear_completa(_conn(), body, uuid4(), str(uuid4()))


# ── Alta completa ────────────────────────────────────────────────────────────


async def test_alta_guarda_precios_de_catalogo_y_estado_del_servidor(repos: dict) -> None:
    resultado = await _crear_completa(_request(estado="pendiente", anticipo=Decimal("99999")))

    guardado = repos["reservacion"]
    assert guardado["precio_total"] == TOTAL_CORRECTO
    assert guardado["precio_personas_extra"] == Decimal("4800.00")
    assert guardado["precio_extras"] == Decimal("350.00")
    assert guardado["precio_productos"] == Decimal("350.00")
    assert guardado["horas_reservadas"] == 4
    # Lo cobrado de verdad, no lo que dijo el cliente.
    assert guardado["anticipo"] == Decimal("4960")
    assert guardado["estado"] == "confirmada"
    # Extras y productos con el precio del catálogo, no el $1 del request.
    assert repos["crear_extra"].await_args.kwargs["precio_unitario"] == Decimal("350.00")
    assert repos["crear_extra"].await_args.kwargs["cantidad"] == 1
    assert repos["crear_producto"].await_args.kwargs["precio_unitario"] == Decimal("175.00")
    assert resultado.reservacion.estado == "confirmada"


async def test_alta_con_precio_manipulado_responde_409_sin_crear_nada(repos: dict) -> None:
    with pytest.raises(HTTPException) as exc:
        await _crear_completa(_request(precio_total=Decimal("1"), pagado=Decimal("1")))

    assert exc.value.status_code == 409
    assert exc.value.detail["message"] == (
        "El precio de la reservación cambió: $12,400.00. Actualiza la reservación."
    )
    assert repos["reservacion"] == {}
    repos["crear_extra"].assert_not_awaited()
    repos["completar"].assert_not_awaited()


async def test_alta_rechaza_40_invitados_en_paquete_de_30(repos: dict) -> None:
    with pytest.raises(HTTPException) as exc:
        await _crear_completa(_request(numero_personas=40))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "CUPO_PAQUETE"
    assert repos["reservacion"] == {}


async def test_alta_sin_anticipo_se_rechaza(repos: dict) -> None:
    body = _request()
    body.pagos = []
    with pytest.raises(HTTPException) as exc:
        await _crear_completa(body)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "ANTICIPO_INSUFICIENTE"


async def test_alta_exige_el_anticipo_del_paquete_no_el_30(repos: dict) -> None:
    # 30 % de 12400 = 3720 no alcanza: Premium pide 40 % = 4960.
    with pytest.raises(HTTPException) as exc:
        await _crear_completa(_request(pagado=Decimal("3720")))
    assert exc.value.detail["code"] == "ANTICIPO_INSUFICIENTE"


async def test_alta_descuenta_el_cambio_de_lo_cobrado(repos: dict) -> None:
    # Entregó $5,000 para un anticipo de $4,960: se le devolvieron $40.
    await _crear_completa(_request(pagado=Decimal("4960"), cambio=Decimal("40")))
    assert repos["reservacion"]["anticipo"] == Decimal("4960")
    assert repos["completar"].await_args.args[1].cambio == Decimal("40.00")


@pytest.mark.parametrize("dias", [0, 3, 7])
async def test_alta_a_7_dias_o_menos_exige_el_total(repos: dict, dias: int) -> None:
    with pytest.raises(HTTPException) as exc:
        await _crear_completa(_request(fecha_evento=HOY + timedelta(days=dias)))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "LIQUIDACION_REQUERIDA"
    assert repos["reservacion"] == {}

    await _crear_completa(_request(fecha_evento=HOY + timedelta(days=dias), pagado=TOTAL_CORRECTO))
    assert repos["reservacion"]["anticipo"] == TOTAL_CORRECTO


async def test_alta_rechaza_extra_inactivo(repos: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        extras_repository, "obtener", AsyncMock(return_value={**EXTRA_ANIMADOR, "activo": False})
    )
    with pytest.raises(HTTPException) as exc:
        await _crear_completa(_request())
    assert exc.value.status_code == 409


async def test_alta_rechaza_producto_de_otra_sucursal(
    repos: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        producto_repository,
        "obtener",
        AsyncMock(return_value=_producto(sucursal_id=str(OTRA_SUCURSAL_ID))),
    )
    with pytest.raises(HTTPException) as exc:
        await _crear_completa(_request())
    assert exc.value.status_code == 422


async def test_alta_rechaza_paquete_de_otra_sucursal(
    repos: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        paquetes_repository,
        "obtener",
        AsyncMock(return_value={**PAQUETE_PREMIUM, "sucursal_id": OTRA_SUCURSAL_ID}),
    )
    with pytest.raises(HTTPException) as exc:
        await _crear_completa(_request())
    assert exc.value.status_code == 422


# ── Alta sin cobro (POST /reservaciones) ─────────────────────────────────────


async def test_alta_simple_queda_pendiente_sin_anticipo(repos: dict) -> None:
    body = _reservacion(
        precio_total=Decimal("11700.00"), estado="confirmada", anticipo=Decimal("5000")
    )
    await reservaciones.crear(_conn(), body, str(uuid4()))
    assert repos["reservacion"]["estado"] == "pendiente"
    assert repos["reservacion"]["anticipo"] == Decimal(0)


async def test_alta_simple_a_7_dias_se_rechaza(repos: dict) -> None:
    body = _reservacion(precio_total=Decimal("11700.00"), fecha_evento=HOY + timedelta(days=7))
    with pytest.raises(HTTPException) as exc:
        await reservaciones.crear(_conn(), body, str(uuid4()))
    assert exc.value.detail["code"] == "LIQUIDACION_REQUERIDA"


async def test_alta_simple_con_precio_manipulado_responde_409(repos: dict) -> None:
    with pytest.raises(HTTPException) as exc:
        await reservaciones.crear(_conn(), _reservacion(precio_total=Decimal("1")), str(uuid4()))
    assert exc.value.status_code == 409


# ── Edición (agregar horas / personalizar) ───────────────────────────────────


def _existente(**cambios: Any) -> dict[str, Any]:
    datos = {
        "id": uuid4(),
        "sucursal_id": SUCURSAL_ID,
        "paquete_id": PAQUETE_ID,
        "activo": True,
        "estado": "confirmada",
        "fecha_evento": HOY + timedelta(days=30),
        "notas": None,
        "numero_personas": 20,
        "horas_reservadas": 4,
        "hora_inicio": time(11, 0),
        "hora_fin": time(15, 0),
        "precio_base": Decimal("6900.00"),
        "precio_personas_extra": Decimal("4800.00"),
        "precio_horas": Decimal("0"),
        "precio_productos": Decimal("875.00"),
        "precio_extras": Decimal("1240.00"),
        "descuento": Decimal("0"),
        "precio_total": Decimal("13815.00"),
        "monto_pagado": Decimal("7526.00"),
    }
    datos.update(cambios)
    return datos


@pytest.fixture
def edicion(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    actual = _existente()
    monkeypatch.setattr(paquetes_repository, "obtener", AsyncMock(return_value=PAQUETE_PREMIUM))
    monkeypatch.setattr(reservaciones_repository, "hoy_en_sucursal", AsyncMock(return_value=HOY))
    monkeypatch.setattr(
        reservaciones_repository, "obtener_para_actualizar", AsyncMock(return_value=actual)
    )
    actualizar = AsyncMock(return_value=None)
    monkeypatch.setattr(reservaciones_repository, "actualizar", actualizar)
    return {"actual": actual, "actualizar": actualizar}


async def test_agregar_hora_recalcula_en_el_servidor(edicion: dict) -> None:
    # 5 h: pulseras 20*60*5 = 6000 -> total 13815 + 1200 = 15015.
    body = ReservacionesUpdate(
        horas_reservadas=5,
        hora_fin=time(16, 0),
        precio_personas_extra=Decimal("6000"),
        precio_total=Decimal("15015"),
    )
    with pytest.raises(HTTPException):  # actualizar() simulado devuelve None -> 404
        await reservaciones.actualizar(_conn(), uuid4(), body)
    updates = edicion["actualizar"].await_args.args[2]
    assert updates["precio_personas_extra"] == Decimal("6000.00")
    assert updates["precio_total"] == Decimal("15015.00")


async def test_agregar_hora_con_total_manipulado_responde_409(edicion: dict) -> None:
    body = ReservacionesUpdate(horas_reservadas=5, precio_total=Decimal("13815"))
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(_conn(), uuid4(), body)
    assert exc.value.status_code == 409
    assert "$15,015.00" in exc.value.detail["message"]
    edicion["actualizar"].assert_not_awaited()


async def test_personalizar_fuera_del_cupo_del_paquete_se_rechaza(edicion: dict) -> None:
    body = ReservacionesUpdate(numero_personas=40)
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(_conn(), uuid4(), body)
    assert exc.value.status_code == 422
    edicion["actualizar"].assert_not_awaited()


async def test_reducir_por_debajo_de_lo_pagado_responde_409(edicion: dict) -> None:
    edicion["actual"]["monto_pagado"] = Decimal("13815.00")
    body = ReservacionesUpdate(horas_reservadas=3)
    with pytest.raises(HTTPException) as exc:
        await reservaciones.actualizar(_conn(), uuid4(), body)
    assert exc.value.status_code == 409
    assert "ya pagado" in exc.value.detail["message"]


async def test_patch_ya_no_acepta_precio_base_ni_descuento_del_cliente(edicion: dict) -> None:
    body = ReservacionesUpdate.model_validate(
        {"notas": "x", "precio_base": "1", "descuento": "99999", "anticipo": "99999"}
    )
    with pytest.raises(HTTPException):
        await reservaciones.actualizar(_conn(), uuid4(), body)
    assert edicion["actualizar"].await_args.args[2] == {"notas": "x"}
