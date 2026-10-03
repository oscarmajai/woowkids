"""Estancias, ola 4 (paquete Q7), sin BD: los repositorios se simulan.

- N4: el check-in sube la INE y las fotos de llegada a MinIO al final de la
  transacción; si algo falla antes no sube nada, y si falla después de subir
  (incluida la confirmación) borra lo subido.
- N5: reimpresión del comprobante con un código nuevo del portal de padres.
- N6: el check-in no acepta 0 horas.
- N8: los cobros de estancia exigen la referencia si el método la pide (M11).
- Tramos contiguos: el precio no depende del orden de los tramos.
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
from app.services.tramos_estancia import precio_por_hora
from fastapi import HTTPException
from pydantic import ValidationError

SUCURSAL = uuid4()
EFECTIVO = uuid4()
TARJETA = uuid4()
METODOS = {
    EFECTIVO: {"nombre": "Efectivo", "requiere_referencia": False, "activo": True},
    TARJETA: {"nombre": "Tarjeta", "requiere_referencia": True, "activo": True},
}
TRAMOS = [{"min_horas": 1, "max_horas": 5, "precio": 60}]


class _FalloAlConfirmarError(Exception):
    pass


def _conn(falla_al_confirmar: bool = False) -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def transaccion() -> Any:
        yield
        if falla_al_confirmar:
            raise _FalloAlConfirmarError()

    conn.transaction = transaccion
    return conn


async def _obtener_metodo(_conn: Any, metodo_id: UUID, _sucursal: Any = None) -> Any:
    return METODOS.get(metodo_id)


@pytest.fixture
def metodos(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = pagos_estancia.metodos_pago_repository
    monkeypatch.setattr(repo, "obtener_ids_por_tipo", AsyncMock(return_value={EFECTIVO}))
    monkeypatch.setattr(repo, "obtener", AsyncMock(side_effect=_obtener_metodo))


@pytest.fixture
def checkin(monkeypatch: pytest.MonkeyPatch, metodos: None) -> dict[str, Any]:
    eventos: list[str] = []

    def registra(nombre: str, retorno: Any = None) -> AsyncMock:
        async def efecto(*_args: Any, **_kwargs: Any) -> Any:
            eventos.append(nombre)
            return retorno

        return AsyncMock(side_effect=efecto)

    m = estancias
    mocks: dict[str, Any] = {
        "eventos": eventos,
        "upload": registra("upload"),
        "delete": AsyncMock(),
        "pago_create": AsyncMock(),
        "emitir": registra("emitir", "codigo-prueba"),
    }
    monkeypatch.setattr(m, "esta_disponible_para_asignar", AsyncMock(return_value=True))
    monkeypatch.setattr(m, "get_tutores_by_phone", AsyncMock(return_value=[]))
    monkeypatch.setattr(m, "tutor_create", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(m, "validar_y_leer", AsyncMock(return_value=b"jpg"))
    monkeypatch.setattr(m, "upload_bytes", mocks["upload"])
    monkeypatch.setattr(m, "delete_objects", mocks["delete"])
    monkeypatch.setattr(m, "registro_create", registra("registro_create"))
    monkeypatch.setattr(m, "foto_create", registra("foto_create"))
    monkeypatch.setattr(m, "nino_create", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(
        m,
        "get_producto_estancia_by_branch_id",
        AsyncMock(return_value={"id": uuid4(), "config_estancia": TRAMOS, "precio_unitario": 0}),
    )
    monkeypatch.setattr(m, "insert_detalle_registro", registra("insert_detalle"))
    monkeypatch.setattr(m, "pago_create", mocks["pago_create"])
    monkeypatch.setattr(m, "registrar_movimiento_caja", AsyncMock())
    monkeypatch.setattr(m, "registrar_cambio_caja", AsyncMock())
    monkeypatch.setattr(m.lealtad_service, "otorgar_puntos", AsyncMock())
    monkeypatch.setattr(m, "registro_update_total", AsyncMock())
    monkeypatch.setattr(m, "change_registro_estado", registra("activar"))
    monkeypatch.setattr(m.manager, "broadcast", AsyncMock())
    monkeypatch.setattr(m, "emitir_codigo_acceso", mocks["emitir"])
    return mocks


def _onboarding(
    horas: int = 2,
    monto: float = 120.0,
    metodo: UUID = EFECTIVO,
    referencia: str | None = None,
) -> OnboardingRequest:
    return OnboardingRequest(
        sucursalId=SUCURSAL,
        tutor=TutorIn(nombreCompleto="Ana Gómez", telefono="3312345678"),
        parentesco="Madre",
        detalles=[
            DetalleIn(
                nino=NinoIn(nombreCompleto="Leo", edad=5, notas="Alérgico al cacahuate"),
                cantidad=horas,
                pulseraId=uuid4(),
            )
        ],
        pagos=[PagoIn(metodoPagoId=metodo, monto=monto, referencia=referencia)],
    )


async def _registrar(
    data: OnboardingRequest, conn: MagicMock | None = None, llegadas: int = 2
) -> dict[str, Any]:
    return await estancias.create_estancia(
        conn or _conn(), data, MagicMock(), [MagicMock()] * llegadas, uuid4(), str(uuid4())
    )


# --- N4 ------------------------------------------------------------------------


async def test_n4_las_fotos_se_suben_despues_de_todos_los_insert(
    checkin: dict[str, Any],
) -> None:
    await _registrar(_onboarding())

    eventos = checkin["eventos"]
    assert eventos.count("upload") == 3  # INE + 2 de llegada
    primera_subida = eventos.index("upload")
    for paso in ("registro_create", "foto_create", "insert_detalle", "activar", "emitir"):
        assert eventos.index(paso) < primera_subida, paso
    llaves = [c.args[0] for c in checkin["upload"].await_args_list]
    assert llaves[0].startswith("uploads/identificaciones/")
    assert all(k.startswith("uploads/llegadas/") for k in llaves[1:])
    checkin["delete"].assert_not_awaited()


async def test_n4_si_el_cobro_no_cuadra_no_sube_nada(checkin: dict[str, Any]) -> None:
    with pytest.raises(HTTPException) as exc:
        await _registrar(_onboarding(monto=1.0))
    assert exc.value.status_code == 409
    checkin["upload"].assert_not_awaited()
    # Nada que borrar: no se subió nada.
    checkin["delete"].assert_awaited_once_with([])


async def test_n4_si_la_transaccion_no_se_confirma_borra_lo_subido(
    checkin: dict[str, Any],
) -> None:
    with pytest.raises(_FalloAlConfirmarError):
        await _registrar(_onboarding(), conn=_conn(falla_al_confirmar=True))

    subidas = [c.args[0] for c in checkin["upload"].await_args_list]
    assert len(subidas) == 3
    checkin["delete"].assert_awaited_once_with(subidas)


async def test_n4_si_falla_una_subida_borra_las_anteriores(checkin: dict[str, Any]) -> None:
    llamadas = 0

    async def falla_la_segunda(llave: str, *_args: Any) -> None:
        nonlocal llamadas
        llamadas += 1
        if llamadas == 2:
            raise RuntimeError("MinIO caído")

    checkin["upload"].side_effect = falla_la_segunda
    with pytest.raises(RuntimeError):
        await _registrar(_onboarding())
    primera = checkin["upload"].await_args_list[0].args[0]
    checkin["delete"].assert_awaited_once_with([primera])


# --- N6 ------------------------------------------------------------------------


@pytest.mark.parametrize("horas", [0, -1])
def test_n6_el_checkin_no_acepta_cero_horas(horas: int) -> None:
    with pytest.raises(ValidationError):
        DetalleIn(nino=NinoIn(nombreCompleto="Leo", edad=5), cantidad=horas, pulseraId=uuid4())


def test_n6_una_hora_es_valida() -> None:
    detalle = DetalleIn(nino=NinoIn(nombreCompleto="Leo", edad=5), cantidad=1, pulseraId=uuid4())
    assert detalle.cantidad == 1


# --- N8 ------------------------------------------------------------------------


async def test_n8_checkin_con_tarjeta_sin_referencia_da_422(checkin: dict[str, Any]) -> None:
    with pytest.raises(HTTPException) as exc:
        await _registrar(_onboarding(metodo=TARJETA, referencia="   "))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "REFERENCIA_REQUERIDA"
    checkin["pago_create"].assert_not_awaited()
    checkin["upload"].assert_not_awaited()


async def test_n8_checkin_con_referencia_la_guarda(checkin: dict[str, Any]) -> None:
    await _registrar(_onboarding(metodo=TARJETA, referencia=" A-123 "))
    args = checkin["pago_create"].await_args.args
    assert args[3] == TARJETA
    assert args[6] == "A-123"


async def test_n8_checkin_con_metodo_inexistente_da_422(checkin: dict[str, Any]) -> None:
    with pytest.raises(HTTPException) as exc:
        await _registrar(_onboarding(metodo=uuid4()))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "METODO_PAGO_INVALIDO"


@pytest.fixture
def checkout(monkeypatch: pytest.MonkeyPatch, metodos: None) -> dict[str, AsyncMock]:
    detalle = {
        "sucursal_id": SUCURSAL,
        "registros_id": uuid4(),
        "salida": None,
        "precio": Decimal("50.00"),
        # 1 h 20 min excedido: 2 h extra -> $100.
        "salida_esperada": datetime.now(UTC) - timedelta(minutes=80),
    }
    mocks = {"pago_create": AsyncMock(), "salida": AsyncMock()}
    m = chekouts
    monkeypatch.setattr(m, "get_detalle_registro_by_id", AsyncMock(return_value=detalle))
    monkeypatch.setattr(m, "put_hora_salida_by_id", mocks["salida"])
    monkeypatch.setattr(m, "make_extra_charge", AsyncMock())
    monkeypatch.setattr(m, "registro_add_total", AsyncMock())
    monkeypatch.setattr(m, "pago_create", mocks["pago_create"])
    monkeypatch.setattr(m, "registrar_movimiento_caja", AsyncMock())
    monkeypatch.setattr(m, "count_detalles_registro_abiertos", AsyncMock(return_value=1))
    monkeypatch.setattr(m.manager, "broadcast", AsyncMock())
    return mocks


async def test_n8_checkout_con_tarjeta_sin_referencia_no_da_la_salida(
    checkout: dict[str, AsyncMock],
) -> None:
    with pytest.raises(HTTPException) as exc:
        await chekouts.create_chekout(
            _conn(), uuid4(), uuid4(), [PagoIn(metodoPagoId=TARJETA, monto=100.0)], str(uuid4())
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "REFERENCIA_REQUERIDA"
    checkout["salida"].assert_not_awaited()
    checkout["pago_create"].assert_not_awaited()


async def test_n8_checkout_guarda_la_referencia(checkout: dict[str, AsyncMock]) -> None:
    pago = PagoIn(metodoPagoId=TARJETA, monto=100.0, referencia="VOUCHER-9")
    await chekouts.create_chekout(_conn(), uuid4(), uuid4(), [pago], str(uuid4()))
    assert checkout["pago_create"].await_args.args[6] == "VOUCHER-9"


async def test_n8_pago_extra_con_tarjeta_sin_referencia_da_422(
    monkeypatch: pytest.MonkeyPatch, metodos: None
) -> None:
    pago_create = AsyncMock()
    monkeypatch.setattr(pagos_estancia, "pago_create", pago_create)
    monkeypatch.setattr(
        pagos_estancia,
        "obtener_saldo_para_cobro",
        AsyncMock(
            return_value={"sucursal_id": SUCURSAL, "total": Decimal("100"), "pagado_neto": 0}
        ),
    )
    body = PagoEstanciaExtraRequest(pagos=[PagoIn(metodoPagoId=TARJETA, monto=50.0)])
    with pytest.raises(HTTPException) as exc:
        await pagos_estancia.pago_create_service(
            _conn(), body, SUCURSAL, uuid4(), uuid4(), str(uuid4())
        )
    assert exc.value.status_code == 422
    pago_create.assert_not_awaited()


# --- N5 ------------------------------------------------------------------------


def _registro(**cambios: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "sucursal_id": SUCURSAL,
        "estado": "A",
        "total": Decimal("240.00"),
        "creado": datetime(2026, 10, 3, 18, 0, tzinfo=UTC),
        "tutor": "Ana Gómez",
        "telefono": "3312345678",
        "sucursal": "Zapopan",
        "cajero": "Diego",
    } | cambios


NINO_DENTRO = {
    "nombre": "Leo",
    "edad": 5,
    "notas": "Alérgico al cacahuate",
    "pulsera": "WK-0000001",
    "horas": 2,
    "salida_esperada": datetime(2026, 10, 3, 20, 0, tzinfo=UTC),
}


@pytest.fixture
def reimpresion(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "registro": AsyncMock(return_value=_registro()),
        "ninos": AsyncMock(return_value=[NINO_DENTRO]),
        "emitir": AsyncMock(return_value="codigo-nuevo"),
    }
    monkeypatch.setattr(estancias, "get_registro_para_comprobante", mocks["registro"])
    monkeypatch.setattr(estancias, "get_ninos_en_estancia_de_registro", mocks["ninos"])
    monkeypatch.setattr(estancias, "emitir_codigo_acceso", mocks["emitir"])
    return mocks


async def test_n5_reimprimir_emite_un_codigo_nuevo_con_las_notas(
    reimpresion: dict[str, AsyncMock],
) -> None:
    registro_id = uuid4()
    usuario = uuid4()
    datos = await estancias.reimprimir_comprobante(_conn(), registro_id, SUCURSAL, usuario)

    reimpresion["emitir"].assert_awaited_once()
    assert reimpresion["emitir"].await_args.args[1:] == (registro_id, usuario)
    assert datos["codigoAccesoPadres"] == "codigo-nuevo"
    assert datos["ninos"][0]["notas"] == "Alérgico al cacahuate"
    assert datos["ninos"][0]["pulsera"] == "WK-0000001"
    assert datos["total"] == 240.0


async def test_n5_registro_de_otra_sucursal_da_404(reimpresion: dict[str, AsyncMock]) -> None:
    reimpresion["registro"].return_value = _registro(sucursal_id=uuid4())
    with pytest.raises(HTTPException) as exc:
        await estancias.reimprimir_comprobante(_conn(), uuid4(), SUCURSAL, uuid4())
    assert exc.value.status_code == 404
    reimpresion["emitir"].assert_not_awaited()


@pytest.mark.parametrize("estado", ["C", "P"])
async def test_n5_registro_cerrado_no_se_reimprime(
    reimpresion: dict[str, AsyncMock], estado: str
) -> None:
    reimpresion["registro"].return_value = _registro(estado=estado)
    with pytest.raises(HTTPException) as exc:
        await estancias.reimprimir_comprobante(_conn(), uuid4(), SUCURSAL, uuid4())
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "REGISTRO_NO_ACTIVO"
    reimpresion["emitir"].assert_not_awaited()


async def test_n5_sin_ninos_dentro_no_se_reimprime(reimpresion: dict[str, AsyncMock]) -> None:
    reimpresion["ninos"].return_value = []
    with pytest.raises(HTTPException) as exc:
        await estancias.reimprimir_comprobante(_conn(), uuid4(), SUCURSAL, uuid4())
    assert exc.value.status_code == 409
    reimpresion["emitir"].assert_not_awaited()


def test_n5_la_ruta_exige_el_permiso_de_checkin() -> None:
    from app.main import app

    rutas = [
        r
        for r in app.routes
        if getattr(r, "path", "") == "/api/estancias/registros/{registro_id}/comprobante"
    ]
    assert len(rutas) == 1
    dependencias = [d.call for d in rutas[0].dependant.dependencies]  # type: ignore[attr-defined]
    nombres = {getattr(d, "__qualname__", "") for d in dependencias}
    assert any("require_permission" in n for n in nombres)


# --- Tramos contiguos --------------------------------------------------------


def test_tramos_contiguos_el_extremo_compartido_es_del_tramo_que_termina_ahi() -> None:
    tramos = [
        {"min_horas": 1, "max_horas": 2, "precio": 130},
        {"min_horas": 0, "max_horas": 1, "precio": 150},
    ]
    # El orden en que se guardaron no importa.
    assert precio_por_hora(tramos, 1) == Decimal("150")
    assert precio_por_hora(tramos, 2) == Decimal("130")
    assert precio_por_hora(list(reversed(tramos)), 1) == Decimal("150")


def test_tramos_sin_extremos_compartidos_se_cotizan_igual_que_antes() -> None:
    tramos = [
        {"min_horas": 4, "max_horas": 8, "precio": 110},
        {"min_horas": 1, "max_horas": 1, "precio": 150},
        {"min_horas": 2, "max_horas": 3, "precio": 130},
    ]
    assert [precio_por_hora(tramos, h) for h in (1, 2, 3, 4, 8)] == [
        Decimal("150"),
        Decimal("130"),
        Decimal("130"),
        Decimal("110"),
        Decimal("110"),
    ]
    # Fuera de todos los tramos: el de min_horas más bajo, como antes.
    assert precio_por_hora(tramos, 12) == Decimal("150")
    assert precio_por_hora([], 2) is None
