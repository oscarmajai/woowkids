"""Segregación de funciones en el cierre de caja.

Reglas que decidió el dueño del producto:
- Nadie autoriza el cierre de su propio turno: si el dueño del turno es un
  administrador, lo autoriza otro administrador de la sucursal o un
  AdministradorSistema (403 AUTORIZADOR_ES_DUENO_TURNO).
- El token del PIN de administrador se separa por propósito: uno emitido para
  cancelar (o devolver) una orden no sirve para cerrar la caja, ni al revés.
- En la revisión del cierre, un administrador con PIN configurado solo entra
  con su PIN; sin PIN se sigue aceptando su contraseña.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from app.core.security import hash_password
from app.core.utils import get_mexico_now
from app.exceptions import PinTokenPropositoError
from app.schemas.caja import ConfirmarCierrePayload, RevisionAdminPayload
from app.services import pin_caja_service, turnos_caja_service
from app.services.pin_caja_service import (
    PROPOSITO_CANCELAR,
    PROPOSITO_CERRAR,
    AutorizadorEsDuenoTurnoError,
    AutorizadorNoValidoError,
)
from app.services.turnos_caja_service import (
    CredencialesAdminInvalidasError,
    PropositoPinInvalidoError,
)

from tests.unit.pin_fakes import ConexionConTransaccion, LimiteEnMemoria

SVC = "app.services.turnos_caja_service"
PIN_SVC = "app.services.pin_caja_service"
SUC = UUID("aaaaaaaa-0000-0000-0000-00000000000a")
APERTURA_ID = str(uuid4())
# El dueño del turno es un administrador que abrió caja.
DUENO_ID = uuid4()
OTRO_ADMIN_ID = uuid4()

PIN_HASH = hash_password("4821")
PASS_HASH = hash_password("contraseña-larga")


def _autorizador(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": OTRO_ADMIN_ID,
        "email": "otro.admin@woowkids.test",
        "pin_hash": PIN_HASH,
        "password_hash": PASS_HASH,
        "nombre_completo": "Otro Admin",
        "rol": "Administrador",
        "tiene_permiso": True,
        "en_sucursal": True,
    }
    base.update(overrides)
    return base


def _apertura(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": APERTURA_ID,
        "cajero_id": DUENO_ID,
        "estado": "EN_CORTE",
        "fondo_inicial": Decimal("1000"),
        "monto_declarado": Decimal("1000"),
        "token_admin_jti": None,
        "conteo_json": None,
        "sucursal_id": SUC,
    }
    base.update(overrides)
    return base


@pytest.fixture
def limite(monkeypatch: pytest.MonkeyPatch) -> LimiteEnMemoria:
    return LimiteEnMemoria().instalar(monkeypatch)


def _buscar(monkeypatch: pytest.MonkeyPatch, fila: dict[str, Any] | None) -> AsyncMock:
    buscar = AsyncMock(return_value=fila)
    monkeypatch.setattr(f"{PIN_SVC}.user_repository.get_autorizador_por_email", buscar)
    return buscar


@pytest.fixture
def pin_admin(monkeypatch: pytest.MonkeyPatch, limite: LimiteEnMemoria) -> AsyncMock:
    monkeypatch.setattr(f"{SVC}.get_apertura_por_id", AsyncMock(return_value=_apertura()))
    emitir = AsyncMock(return_value="token")
    monkeypatch.setattr(f"{SVC}._emitir_token_pin", emitir)
    return emitir


@pytest.fixture
def confirmar(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    monkeypatch.setattr(turnos_caja_service.settings, "exigir_pin_token", True)
    mocks = {
        "crear_cierre_caja": AsyncMock(return_value={"id": uuid4()}),
        "actualizar_estado_apertura": AsyncMock(),
        "_calcular_balance": AsyncMock(return_value=(Decimal("0"), Decimal("0"), Decimal("0"), [])),
    }
    for nombre, mock in mocks.items():
        monkeypatch.setattr(f"{SVC}.{nombre}", mock)
    return mocks


def _apertura_revisada(admin_id: UUID) -> dict[str, Any]:
    return _apertura(
        token_admin_jti=str(admin_id),
        conteo_json=json.dumps({"desglose_efectivo": {"total": "1000"}}),
    )


async def _confirmar() -> Any:
    return await turnos_caja_service.confirmar_cierre(
        ConexionConTransaccion(),  # type: ignore[arg-type]
        str(DUENO_ID),
        ConfirmarCierrePayload(turno_id=APERTURA_ID, token_pin_cajero="tc", token_pin_admin="ta"),
    )


# ── El token del PIN de administrador se separa por propósito ──────────────


async def test_validar_pin_admin_emite_el_token_con_su_proposito(
    monkeypatch: pytest.MonkeyPatch, pin_admin: AsyncMock
) -> None:
    _buscar(monkeypatch, _autorizador())
    for proposito in (PROPOSITO_CERRAR, PROPOSITO_CANCELAR):
        resp = await turnos_caja_service.validar_pin_admin(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            APERTURA_ID,
            "otro.admin@woowkids.test",
            "4821",
            proposito=proposito,
        )
        assert resp["token_pin"] == "token"
        assert pin_admin.await_args.args[-1] == proposito


async def test_validar_pin_admin_sin_proposito_emite_para_cancelar(
    monkeypatch: pytest.MonkeyPatch, pin_admin: AsyncMock
) -> None:
    """Retrocompatibilidad: los llamadores anteriores a la separación por propósito eran las
    cancelaciones de órdenes cobradas (el cierre ya manda ``cerrar``)."""
    _buscar(monkeypatch, _autorizador())
    await turnos_caja_service.validar_pin_admin(
        ConexionConTransaccion(),  # type: ignore[arg-type]
        APERTURA_ID,
        "otro.admin@woowkids.test",
        "4821",
    )
    assert pin_admin.await_args.args[-1] == PROPOSITO_CANCELAR


async def test_validar_pin_admin_rechaza_un_proposito_desconocido(
    monkeypatch: pytest.MonkeyPatch, pin_admin: AsyncMock
) -> None:
    buscar = _buscar(monkeypatch, _autorizador())
    with pytest.raises(PropositoPinInvalidoError) as exc:
        await turnos_caja_service.validar_pin_admin(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            APERTURA_ID,
            "otro.admin@woowkids.test",
            "4821",
            proposito="todo",
        )
    assert exc.value.status_code == 422
    buscar.assert_not_called()


def _tokens(monkeypatch: pytest.MonkeyPatch, proposito: str) -> AsyncMock:
    fila = {
        "token": "t",
        "usuario_id": OTRO_ADMIN_ID,
        "turno_id": APERTURA_ID,
        "rol": "admin",
        "proposito": proposito,
        "expira": get_mexico_now() + timedelta(minutes=5),
        "usado": False,
    }
    monkeypatch.setattr(f"{SVC}.pin_token_repository.obtener_token", AsyncMock(return_value=fila))
    marcar = AsyncMock()
    monkeypatch.setattr(f"{SVC}.pin_token_repository.marcar_usado", marcar)
    return marcar


async def test_token_de_cancelar_no_sirve_para_cerrar(monkeypatch: pytest.MonkeyPatch) -> None:
    marcar = _tokens(monkeypatch, PROPOSITO_CANCELAR)
    with pytest.raises(PinTokenPropositoError) as exc:
        await turnos_caja_service._validar_y_consumir_token_pin(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            "t",
            APERTURA_ID,
            "admin",
            PROPOSITO_CERRAR,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "PIN_TOKEN_PROPOSITO_INVALIDO"
    assert "cerrar la caja" in exc.value.detail["message"]
    marcar.assert_not_called()


async def test_token_de_cerrar_no_sirve_para_cancelar(monkeypatch: pytest.MonkeyPatch) -> None:
    marcar = _tokens(monkeypatch, PROPOSITO_CERRAR)
    with pytest.raises(PinTokenPropositoError):
        await turnos_caja_service.consumir_token_pin_admin(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            "t",
            APERTURA_ID,
        )
    marcar.assert_not_called()


async def test_token_de_cancelar_sirve_para_cancelar(monkeypatch: pytest.MonkeyPatch) -> None:
    marcar = _tokens(monkeypatch, PROPOSITO_CANCELAR)
    admin_id = await turnos_caja_service.consumir_token_pin_admin(
        ConexionConTransaccion(),  # type: ignore[arg-type]
        "t",
        APERTURA_ID,
    )
    assert admin_id == str(OTRO_ADMIN_ID)
    marcar.assert_awaited_once()


async def test_confirmar_consume_los_tokens_con_proposito_cerrar(
    monkeypatch: pytest.MonkeyPatch, confirmar: dict[str, AsyncMock]
) -> None:
    monkeypatch.setattr(
        f"{SVC}.bloquear_apertura", AsyncMock(return_value=_apertura_revisada(OTRO_ADMIN_ID))
    )
    consumir = AsyncMock(return_value={"usuario_id": OTRO_ADMIN_ID})
    monkeypatch.setattr(f"{SVC}._validar_y_consumir_token_pin", consumir)
    resp = await _confirmar()
    assert resp.estado == "CERRADO"
    assert [c.args[3:] for c in consumir.await_args_list] == [
        ("cajero", PROPOSITO_CERRAR),
        ("admin", PROPOSITO_CERRAR),
    ]
    confirmar["crear_cierre_caja"].assert_awaited_once()


# ── Nadie autoriza el cierre de su propio turno ────────────────────────────


async def test_buscar_autorizador_rechaza_al_dueno_del_turno_sin_probar_el_pin(
    monkeypatch: pytest.MonkeyPatch, limite: LimiteEnMemoria
) -> None:
    _buscar(monkeypatch, _autorizador(id=DUENO_ID))
    with pytest.raises(AutorizadorEsDuenoTurnoError) as exc:
        await pin_caja_service.verificar_pin_autorizador(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            email="dueno@woowkids.test",
            pin="4821",
            sucursal_id=SUC,
            dueno_turno_id=str(DUENO_ID),
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "AUTORIZADOR_ES_DUENO_TURNO"
    assert "propio turno" in exc.value.detail["message"]
    # No cuenta como intento fallido: ni siquiera se verificó el PIN.
    assert limite.total() == 0


@pytest.fixture
def revision(monkeypatch: pytest.MonkeyPatch, limite: LimiteEnMemoria) -> dict[str, AsyncMock]:
    mocks = {
        "get_dueno_y_sucursal_apertura": AsyncMock(
            return_value={"id": APERTURA_ID, "cajero_id": DUENO_ID, "sucursal_id": SUC}
        ),
        "bloquear_apertura": AsyncMock(return_value=_apertura()),
        "_calcular_balance": AsyncMock(
            return_value=(Decimal("1000"), Decimal("1000"), Decimal("0"), [])
        ),
        "actualizar_admin_autorizacion": AsyncMock(),
    }
    for nombre, mock in mocks.items():
        monkeypatch.setattr(f"{SVC}.{nombre}", mock)
    return mocks


async def _revisar(secreto: str = "4821") -> Any:
    return await turnos_caja_service.autenticar_admin_revision(
        ConexionConTransaccion(),  # type: ignore[arg-type]
        str(DUENO_ID),
        RevisionAdminPayload(
            turno_id=APERTURA_ID, admin_email="x@woowkids.test", admin_password=secreto
        ),
    )


async def test_revision_admin_dueno_del_turno_es_rechazado(
    monkeypatch: pytest.MonkeyPatch, revision: dict[str, AsyncMock]
) -> None:
    _buscar(monkeypatch, _autorizador(id=DUENO_ID))
    with pytest.raises(AutorizadorEsDuenoTurnoError):
        await _revisar()
    revision["actualizar_admin_autorizacion"].assert_not_called()


async def test_revision_otro_admin_de_la_sucursal_autoriza(
    monkeypatch: pytest.MonkeyPatch, revision: dict[str, AsyncMock]
) -> None:
    _buscar(monkeypatch, _autorizador())
    resp = await _revisar()
    assert resp.autorizado is True
    assert revision["actualizar_admin_autorizacion"].await_args.args[2] == str(OTRO_ADMIN_ID)


async def test_revision_administrador_sistema_autoriza(
    monkeypatch: pytest.MonkeyPatch, revision: dict[str, AsyncMock]
) -> None:
    _buscar(
        monkeypatch,
        _autorizador(rol="AdministradorSistema", en_sucursal=False, tiene_permiso=False),
    )
    resp = await _revisar()
    assert resp.autorizado is True


async def test_revision_admin_de_otra_sucursal_es_rechazado(
    monkeypatch: pytest.MonkeyPatch, revision: dict[str, AsyncMock]
) -> None:
    _buscar(monkeypatch, _autorizador(en_sucursal=False))
    with pytest.raises(AutorizadorNoValidoError):
        await _revisar()
    revision["actualizar_admin_autorizacion"].assert_not_called()


async def test_validar_pin_admin_para_cerrar_rechaza_al_dueno_del_turno(
    monkeypatch: pytest.MonkeyPatch, pin_admin: AsyncMock
) -> None:
    _buscar(monkeypatch, _autorizador(id=DUENO_ID))
    with pytest.raises(AutorizadorEsDuenoTurnoError):
        await turnos_caja_service.validar_pin_admin(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            APERTURA_ID,
            "dueno@woowkids.test",
            "4821",
            proposito=PROPOSITO_CERRAR,
        )
    pin_admin.assert_not_called()


async def test_confirmar_rechaza_si_la_revision_la_autorizo_el_dueno(
    monkeypatch: pytest.MonkeyPatch, confirmar: dict[str, AsyncMock]
) -> None:
    monkeypatch.setattr(
        f"{SVC}.bloquear_apertura", AsyncMock(return_value=_apertura_revisada(DUENO_ID))
    )
    with pytest.raises(AutorizadorEsDuenoTurnoError):
        await _confirmar()
    confirmar["crear_cierre_caja"].assert_not_called()


async def test_confirmar_rechaza_el_token_de_cerrar_emitido_por_el_dueno(
    monkeypatch: pytest.MonkeyPatch, confirmar: dict[str, AsyncMock]
) -> None:
    monkeypatch.setattr(
        f"{SVC}.bloquear_apertura", AsyncMock(return_value=_apertura_revisada(OTRO_ADMIN_ID))
    )
    monkeypatch.setattr(
        f"{SVC}._validar_y_consumir_token_pin",
        AsyncMock(return_value={"usuario_id": DUENO_ID}),
    )
    with pytest.raises(AutorizadorEsDuenoTurnoError):
        await _confirmar()
    confirmar["crear_cierre_caja"].assert_not_called()


# ── Revisión: con PIN configurado solo vale el PIN ─────────────────────────


async def test_revision_admin_con_pin_que_manda_su_contraseña_es_rechazado(
    monkeypatch: pytest.MonkeyPatch, revision: dict[str, AsyncMock], limite: LimiteEnMemoria
) -> None:
    _buscar(monkeypatch, _autorizador())
    with pytest.raises(CredencialesAdminInvalidasError) as exc:
        await _revisar("contraseña-larga")
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "CREDENCIALES_INVALIDAS"
    assert "PIN configurado" in exc.value.detail["message"]
    assert limite.tipos == ["revision"]
    revision["actualizar_admin_autorizacion"].assert_not_called()


async def test_revision_admin_sin_pin_entra_con_su_contraseña(
    monkeypatch: pytest.MonkeyPatch, revision: dict[str, AsyncMock]
) -> None:
    _buscar(monkeypatch, _autorizador(pin_hash=None))
    resp = await _revisar("contraseña-larga")
    assert resp.autorizado is True


async def test_revision_admin_sin_pin_con_contraseña_equivocada_explica_por_que(
    monkeypatch: pytest.MonkeyPatch, revision: dict[str, AsyncMock]
) -> None:
    _buscar(monkeypatch, _autorizador(pin_hash=None))
    with pytest.raises(CredencialesAdminInvalidasError) as exc:
        await _revisar("otra")
    assert "Contraseña incorrecta" in exc.value.detail["message"]
