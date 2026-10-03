"""C2 en estancias: el check-in, el checkout y el pago extra cobran lo que
calcula el servidor, no lo que diga el navegador.

- Check-in (create_estancia): el precio sale de los tramos del producto de
  estancia de la sucursal; el cliente solo manda horas. Los pagos menos el
  cambio tienen que sumar exactamente ese total o se responde 409.
- Checkout (create_chekout): ya recalculaba el excedente con la hora real y
  respondía 409 si lo pagado no coincide; aquí queda demostrado con pruebas.
- Pago extra (pago_create_service): no puede cobrar más que el saldo.

Sin BD: los repositorios se simulan.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.schemas.ninos import NinoIn
from app.schemas.pagos import PagoEstanciaExtraRequest, PagoIn
from app.schemas.registros import DetalleIn, OnboardingRequest
from app.schemas.tutores import TutorIn
from app.services import chekouts, estancias, pagos_estancia
from fastapi import HTTPException

SUCURSAL = uuid4()
EFECTIVO = uuid4()
PRODUCTO_ESTANCIA = uuid4()
# 1-2 h a $60/h, 3-5 h a $50/h.
TRAMOS = [
    {"min_horas": 1, "max_horas": 2, "precio": 60},
    {"min_horas": 3, "max_horas": 5, "precio": 50},
]


def _conn() -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def transaccion() -> Any:
        yield

    conn.transaction = transaccion
    return conn


@pytest.fixture
def checkin(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "insert_detalle": AsyncMock(),
        "pago_create": AsyncMock(),
        "movimiento": AsyncMock(),
        "cambio": AsyncMock(),
        "activar": AsyncMock(),
    }
    m = estancias
    monkeypatch.setattr(
        m.metodos_pago_repository, "obtener_ids_por_tipo", AsyncMock(return_value={EFECTIVO})
    )
    monkeypatch.setattr(m, "esta_disponible_para_asignar", AsyncMock(return_value=True))
    monkeypatch.setattr(m, "get_tutor_by_phone", AsyncMock(return_value={"id": uuid4()}))
    monkeypatch.setattr(m, "validar_y_leer", AsyncMock(return_value=b"jpg"))
    monkeypatch.setattr(m, "upload_bytes", AsyncMock())
    monkeypatch.setattr(m, "registro_create", AsyncMock())
    monkeypatch.setattr(m, "foto_create", AsyncMock())
    monkeypatch.setattr(m, "nino_create", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(
        m,
        "get_producto_estancia_by_branch_id",
        AsyncMock(
            return_value={
                "id": PRODUCTO_ESTANCIA,
                "config_estancia": TRAMOS,
                "precio_unitario": Decimal("0"),
            }
        ),
    )
    monkeypatch.setattr(m, "insert_detalle_registro", mocks["insert_detalle"])
    monkeypatch.setattr(m, "pago_create", mocks["pago_create"])
    monkeypatch.setattr(m, "registrar_movimiento_caja", mocks["movimiento"])
    monkeypatch.setattr(m, "registrar_cambio_caja", mocks["cambio"])
    monkeypatch.setattr(m.lealtad_service, "otorgar_puntos", AsyncMock())
    monkeypatch.setattr(m, "registro_update_total", AsyncMock())
    monkeypatch.setattr(m, "change_registro_estado", mocks["activar"])
    monkeypatch.setattr(m.manager, "broadcast", AsyncMock())
    # A17: el check-in emite el código del portal de padres (fuera de este test).
    monkeypatch.setattr(m, "emitir_codigo_acceso", AsyncMock(return_value="codigo-prueba"))
    return mocks


def _onboarding(horas: list[int], pagos: list[float], cambio: str = "0") -> OnboardingRequest:
    return OnboardingRequest(
        sucursalId=SUCURSAL,
        tutor=TutorIn(nombreCompleto="Ana Gómez", telefono="3312345678"),
        parentesco="Madre",
        detalles=[
            DetalleIn(
                nino=NinoIn(nombreCompleto=f"Niño {i}", edad=5),
                # El cliente manda otro producto: no debe importar.
                productoId=uuid4(),
                cantidad=h,
                pulseraId=uuid4(),
            )
            for i, h in enumerate(horas)
        ],
        pagos=[PagoIn(metodoPagoId=EFECTIVO, monto=m) for m in pagos],
        cambio=Decimal(cambio),
    )


async def _registrar(data: OnboardingRequest) -> dict[str, Any]:
    return await estancias.create_estancia(_conn(), data, MagicMock(), [], uuid4(), str(uuid4()))


async def test_checkin_cobra_con_los_tramos_del_servidor(checkin: dict[str, AsyncMock]) -> None:
    # 2 h a $60 + 4 h a $50 = $320; paga $400 en efectivo con $80 de cambio.
    resultado = await _registrar(_onboarding([2, 4], [400.0], cambio="80"))

    assert resultado["total"] == Decimal("320")
    precios = [c.args[10] for c in checkin["insert_detalle"].await_args_list]
    productos = {c.args[11] for c in checkin["insert_detalle"].await_args_list}
    assert precios == [Decimal("60"), Decimal("50")]
    assert productos == {PRODUCTO_ESTANCIA}
    checkin["activar"].assert_awaited_once()


@pytest.mark.parametrize(
    ("pagos", "cambio"),
    [([1.0], "0"), ([400.0], "0"), ([300.0], "0")],
    ids=["paga_de_menos", "paga_de_mas_sin_cambio", "precio_de_otro_tramo"],
)
async def test_checkin_con_pagos_que_no_cuadran_da_409_y_no_cobra(
    checkin: dict[str, AsyncMock], pagos: list[float], cambio: str
) -> None:
    with pytest.raises(HTTPException) as exc:
        await _registrar(_onboarding([2, 4], pagos, cambio))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "MONTO_NO_COINCIDE"
    assert "$320.00" in exc.value.detail["message"]
    checkin["pago_create"].assert_not_awaited()
    checkin["movimiento"].assert_not_awaited()
    checkin["activar"].assert_not_awaited()


# --- checkout ----------------------------------------------------------------


@pytest.fixture
def checkout(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    detalle = {
        "sucursal_id": SUCURSAL,
        "registros_id": uuid4(),
        "salida": None,
        # Precio por hora fijado en el check-in por el servidor.
        "precio": Decimal("50.00"),
        # Pasó 1 h 20 min de lo contratado: 10 min de tolerancia + 70 min -> 2 h extra.
        "salida_esperada": datetime.now(UTC) - timedelta(minutes=80),
    }
    mocks = {"cargo": AsyncMock(), "pago_create": AsyncMock(), "salida": AsyncMock()}
    m = chekouts
    monkeypatch.setattr(m, "get_detalle_registro_by_id", AsyncMock(return_value=detalle))
    monkeypatch.setattr(m, "put_hora_salida_by_id", mocks["salida"])
    monkeypatch.setattr(m, "make_extra_charge", mocks["cargo"])
    monkeypatch.setattr(m, "registro_add_total", AsyncMock())
    monkeypatch.setattr(m, "pago_create", mocks["pago_create"])
    monkeypatch.setattr(m, "registrar_movimiento_caja", AsyncMock())
    monkeypatch.setattr(m, "count_detalles_registro_abiertos", AsyncMock(return_value=1))
    monkeypatch.setattr(m.manager, "broadcast", AsyncMock())
    return mocks


async def test_checkout_rechaza_un_monto_distinto_al_calculado(
    checkout: dict[str, AsyncMock],
) -> None:
    with pytest.raises(HTTPException) as exc:
        await chekouts.create_chekout(
            _conn(), uuid4(), uuid4(), [PagoIn(metodoPagoId=EFECTIVO, monto=1.0)], str(uuid4())
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["totalExtra"] == 100.0
    checkout["salida"].assert_not_awaited()
    checkout["pago_create"].assert_not_awaited()


async def test_checkout_cobra_el_excedente_calculado_en_el_servidor(
    checkout: dict[str, AsyncMock],
) -> None:
    resultado = await chekouts.create_chekout(
        _conn(), uuid4(), uuid4(), [PagoIn(metodoPagoId=EFECTIVO, monto=100.0)], str(uuid4())
    )
    assert (resultado["horasExtra"], resultado["totalExtra"]) == (2, 100.0)
    # horas, precio unitario y total del cargo extra: los del servidor.
    assert checkout["cargo"].await_args.args[4:7] == (2, 50.0, 100.0)


# --- pago extra ----------------------------------------------------------------


@pytest.fixture
def pago_extra(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {"pago_create": AsyncMock(), "saldo": AsyncMock()}
    m = pagos_estancia
    monkeypatch.setattr(
        m.metodos_pago_repository, "obtener_ids_por_tipo", AsyncMock(return_value={EFECTIVO})
    )
    monkeypatch.setattr(m, "obtener_saldo_para_cobro", mocks["saldo"])
    monkeypatch.setattr(m, "pago_create", mocks["pago_create"])
    monkeypatch.setattr(m, "registrar_movimiento_caja", AsyncMock())
    monkeypatch.setattr(m, "registrar_cambio_caja", AsyncMock())
    return mocks


async def _pagar_extra(monto: float, sucursal: UUID = SUCURSAL) -> None:
    body = PagoEstanciaExtraRequest(pagos=[PagoIn(metodoPagoId=EFECTIVO, monto=monto)])
    await pagos_estancia.pago_create_service(
        _conn(), body, sucursal, uuid4(), uuid4(), str(uuid4())
    )


async def test_pago_extra_no_cobra_mas_que_el_saldo(pago_extra: dict[str, AsyncMock]) -> None:
    pago_extra["saldo"].return_value = {
        "sucursal_id": SUCURSAL,
        "total": Decimal("320.00"),
        "pagado_neto": Decimal("300.00"),
    }
    with pytest.raises(HTTPException) as exc:
        await _pagar_extra(50.0)
    assert exc.value.status_code == 409
    assert "$20.00" in exc.value.detail["message"]
    pago_extra["pago_create"].assert_not_awaited()

    await _pagar_extra(20.0)
    pago_extra["pago_create"].assert_awaited_once()


async def test_pago_extra_de_un_registro_de_otra_sucursal_da_404(
    pago_extra: dict[str, AsyncMock],
) -> None:
    pago_extra["saldo"].return_value = {
        "sucursal_id": uuid4(),
        "total": Decimal("320.00"),
        "pagado_neto": Decimal("0"),
    }
    with pytest.raises(HTTPException) as exc:
        await _pagar_extra(20.0)
    assert exc.value.status_code == 404
    pago_extra["pago_create"].assert_not_awaited()


def test_no_se_cobra_una_estancia_con_los_precios_de_otra_sucursal() -> None:
    from datetime import datetime as dt

    # El check-in y el pago extra usan la regla única de C1 (core/scope.py).
    from app.core.scope import resolver_sucursal_obligatoria
    from app.schemas.auth import TokenData

    cajera = TokenData(
        sub=str(uuid4()), email="c@x.dev", role="Cajero", branch_id=SUCURSAL, jti="j", exp=dt.now()
    )
    assert str(resolver_sucursal_obligatoria(cajera, SUCURSAL)) == str(SUCURSAL)
    with pytest.raises(HTTPException) as exc:
        resolver_sucursal_obligatoria(cajera, uuid4())
    assert exc.value.status_code == 403
