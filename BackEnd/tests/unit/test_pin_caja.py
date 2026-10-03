"""A5 / A15 / A16 (pruebas E2E 2026-10-03): validación de PIN de caja.

- A5: un PIN mal escrito responde 403 (PIN_INVALIDO / CREDENCIALES_INVALIDAS),
  nunca 401, que el front reserva para la sesión vencida.
- A15: cancelar (y el resto del cierre) solo lo hace el dueño del turno o
  quien autoriza cierres en esa sucursal.
- A16: validar-pin-* exigen permiso de caja; con PIN configurado no vale la
  contraseña; límite de intentos; el administrador se busca solo en la
  sucursal del turno y debe tener permiso de autorizar.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.security import hash_password
from app.main import app
from app.schemas.auth import TokenData
from app.services import permission_service, pin_caja_service, turnos_caja_service
from app.services.pin_caja_service import (
    AutorizadorNoValidoError,
    PinBloqueadoError,
    PinInvalidoError,
    credencial_valida,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.unit.pin_fakes import ConexionConTransaccion, LimiteEnMemoria

SVC = "app.services.turnos_caja_service"
PIN_SVC = "app.services.pin_caja_service"
SUC = UUID("aaaaaaaa-0000-0000-0000-00000000000a")
OTRA_SUC = UUID("bbbbbbbb-0000-0000-0000-00000000000b")
DUENO_ID = str(uuid4())
APERTURA_ID = str(uuid4())

PIN_HASH = hash_password("4821")
PASS_HASH = hash_password("contraseña-larga")


def _usuario(rol: str, branch_id: UUID | None = SUC, sub: str | None = None) -> TokenData:
    return TokenData(
        sub=sub or str(uuid4()),
        email=f"{rol.lower()}@woowkids.test",
        role=rol,
        branch_id=branch_id,
        permissions=[],
        jti=str(uuid4()),
        exp=datetime.now(tz=UTC) + timedelta(hours=1),
    )


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


@pytest.fixture
def permisos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caché de permisos como la siembran 021/073 para los roles de caja."""
    caja = {
        "turnos_caja:abrir",
        "turnos_caja:ver_activo",
        "turnos_caja:conteo",
        "turnos_caja:cancelar",
    }
    admin = caja | {"turnos_caja:confirmar", "turnos_caja:revision_admin", "turnos_caja:historial"}
    monkeypatch.setitem(permission_service._cache, "Cajero", frozenset(caja))
    monkeypatch.setitem(permission_service._cache, "Administrador", frozenset(admin))
    monkeypatch.setitem(permission_service._cache, "AdministradorSistema", frozenset(admin))
    monkeypatch.setitem(permission_service._cache, "Cocina", frozenset({"comandas:ver"}))
    monkeypatch.setitem(permission_service._cache, "Inventario", frozenset({"inventario:ver"}))


# ── Reglas puras ────────────────────────────────────────────────────────────


def test_con_pin_configurado_solo_vale_el_pin() -> None:
    assert credencial_valida("4821", PIN_HASH, PASS_HASH)
    assert not credencial_valida("contraseña-larga", PIN_HASH, PASS_HASH)


def test_sin_pin_configurado_vale_la_contraseña() -> None:
    assert credencial_valida("contraseña-larga", None, PASS_HASH)
    assert not credencial_valida("0000", None, PASS_HASH)


def test_revision_con_contraseña_acepta_ambas() -> None:
    assert credencial_valida("contraseña-larga", PIN_HASH, PASS_HASH, acepta_password=True)
    assert credencial_valida("4821", PIN_HASH, PASS_HASH, acepta_password=True)


def test_hash_invalido_no_revienta() -> None:
    assert not credencial_valida("x", "no-es-bcrypt", None)
    assert not credencial_valida("", PIN_HASH, PASS_HASH)


def test_errores_de_pin_no_son_401() -> None:
    """A5: el 401 dispara refresh + reenvío + logout en el interceptor del front."""
    assert PinInvalidoError().status_code == 403
    assert PinInvalidoError().detail["code"] == "PIN_INVALIDO"
    assert turnos_caja_service.CredencialesAdminInvalidasError().status_code == 403
    assert AutorizadorNoValidoError().status_code == 403
    bloqueo = PinBloqueadoError(301)
    assert bloqueo.status_code == 429
    assert "6 minutos" in bloqueo.detail["message"]


# ── Límite de intentos ──────────────────────────────────────────────────────


async def test_limite_bloquea_al_sexto_intento_sin_verificar(limite: LimiteEnMemoria) -> None:
    conn = ConexionConTransaccion()
    usuario = uuid4()
    llamadas: list[int] = []

    def verificar() -> bool:
        llamadas.append(1)
        return False

    for _ in range(pin_caja_service.MAX_FALLOS):
        with pytest.raises(PinInvalidoError):
            await pin_caja_service.verificar_con_limite(
                conn,  # type: ignore[arg-type]
                usuario_id=usuario,
                sucursal_id=SUC,
                tipo="admin",
                verificar=verificar,
                error=PinInvalidoError(),
            )
    with pytest.raises(PinBloqueadoError):
        await pin_caja_service.verificar_con_limite(
            conn,  # type: ignore[arg-type]
            usuario_id=usuario,
            sucursal_id=SUC,
            tipo="admin",
            verificar=lambda: True,
            error=PinInvalidoError(),
        )
    assert len(llamadas) == pin_caja_service.MAX_FALLOS

    # La llave es por sucursal: en otra sucursal sigue habiendo intentos.
    await pin_caja_service.verificar_con_limite(
        conn,  # type: ignore[arg-type]
        usuario_id=usuario,
        sucursal_id=OTRA_SUC,
        tipo="admin",
        verificar=lambda: True,
        error=PinInvalidoError(),
    )


async def test_un_acierto_reinicia_el_contador(limite: LimiteEnMemoria) -> None:
    conn = ConexionConTransaccion()
    usuario = uuid4()
    for _ in range(pin_caja_service.MAX_FALLOS - 1):
        with pytest.raises(PinInvalidoError):
            await pin_caja_service.verificar_con_limite(
                conn,  # type: ignore[arg-type]
                usuario_id=usuario,
                sucursal_id=SUC,
                tipo="cajero",
                verificar=lambda: False,
                error=PinInvalidoError(),
            )
    await pin_caja_service.verificar_con_limite(
        conn,  # type: ignore[arg-type]
        usuario_id=usuario,
        sucursal_id=SUC,
        tipo="cajero",
        verificar=lambda: True,
        error=PinInvalidoError(),
    )
    assert limite.total() == 0


# ── Búsqueda del autorizador ────────────────────────────────────────────────


def _autorizador(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": uuid4(),
        "email": "admin@woowkids.test",
        "pin_hash": PIN_HASH,
        "password_hash": PASS_HASH,
        "nombre_completo": "Admin Patria",
        "rol": "Administrador",
        "tiene_permiso": True,
        "en_sucursal": True,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "fila",
    [
        None,
        _autorizador(en_sucursal=False),  # administrador de otra sucursal
        _autorizador(rol="Cocina", tiene_permiso=False),  # rol sin permiso de autorizar
        _autorizador(rol="Cajero", tiene_permiso=False),
    ],
)
async def test_autorizador_no_valido_responde_403_sin_probar_el_pin(
    fila: dict[str, Any] | None, monkeypatch: pytest.MonkeyPatch, limite: LimiteEnMemoria
) -> None:
    monkeypatch.setattr(
        f"{PIN_SVC}.user_repository.get_autorizador_por_email", AsyncMock(return_value=fila)
    )
    with pytest.raises(AutorizadorNoValidoError):
        await pin_caja_service.verificar_pin_autorizador(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            email="admin@woowkids.test",
            pin="4821",
            sucursal_id=SUC,
        )
    assert limite.total() == 0


async def test_administrador_sistema_autoriza_sin_sucursal(
    monkeypatch: pytest.MonkeyPatch, limite: LimiteEnMemoria
) -> None:
    monkeypatch.setattr(
        f"{PIN_SVC}.user_repository.get_autorizador_por_email",
        AsyncMock(
            return_value=_autorizador(
                rol="AdministradorSistema", en_sucursal=False, tiene_permiso=False
            )
        ),
    )
    fila = await pin_caja_service.verificar_pin_autorizador(
        ConexionConTransaccion(),  # type: ignore[arg-type]
        email="sys@woowkids.test",
        pin="4821",
        sucursal_id=SUC,
    )
    assert fila["rol"] == "AdministradorSistema"


# ── validar_pin_admin / validar_pin_cajero ──────────────────────────────────


@pytest.fixture
def pin_admin(monkeypatch: pytest.MonkeyPatch, limite: LimiteEnMemoria) -> dict[str, AsyncMock]:
    mocks = {
        "get_apertura_por_id": AsyncMock(return_value=_apertura()),
        "_emitir_token_pin": AsyncMock(return_value="token"),
    }
    for nombre, mock in mocks.items():
        monkeypatch.setattr(f"{SVC}.{nombre}", mock)
    buscar = AsyncMock(return_value=_autorizador())
    monkeypatch.setattr(f"{PIN_SVC}.user_repository.get_autorizador_por_email", buscar)
    mocks["buscar"] = buscar
    return mocks


async def test_validar_pin_admin_rechaza_la_contraseña_si_tiene_pin(
    pin_admin: dict[str, AsyncMock],
) -> None:
    conn = ConexionConTransaccion()
    with pytest.raises(PinInvalidoError) as exc:
        await turnos_caja_service.validar_pin_admin(
            conn,  # type: ignore[arg-type]
            APERTURA_ID,
            "admin@woowkids.test",
            "contraseña-larga",
        )
    assert exc.value.status_code == 403
    pin_admin["_emitir_token_pin"].assert_not_called()


async def test_validar_pin_admin_busca_en_la_sucursal_del_turno_con_permiso_de_cierre(
    pin_admin: dict[str, AsyncMock],
) -> None:
    resp = await turnos_caja_service.validar_pin_admin(
        ConexionConTransaccion(),  # type: ignore[arg-type]
        APERTURA_ID,
        "admin@woowkids.test",
        "4821",
    )
    assert resp["token_pin"] == "token"
    _conn, email, sucursal, permiso = pin_admin["buscar"].await_args.args
    assert (email, sucursal, permiso) == ("admin@woowkids.test", SUC, "turnos_caja:confirmar")


async def test_validar_pin_admin_desde_turno_ajeno_responde_403(
    pin_admin: dict[str, AsyncMock], permisos: None
) -> None:
    otra_cajera = _usuario("Cajero")
    with pytest.raises(turnos_caja_service.TurnoAjenoError):
        await turnos_caja_service.validar_pin_admin(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            APERTURA_ID,
            "admin@woowkids.test",
            "4821",
            user_id=otra_cajera.sub,
            solicitante=otra_cajera,
        )
    pin_admin["buscar"].assert_not_called()


async def test_validar_pin_cajero_rechaza_la_contraseña_y_turnos_ajenos(
    monkeypatch: pytest.MonkeyPatch, limite: LimiteEnMemoria, permisos: None
) -> None:
    monkeypatch.setattr(f"{SVC}.get_apertura_por_id", AsyncMock(return_value=_apertura()))
    monkeypatch.setattr(
        f"{SVC}.get_usuario_by_id",
        AsyncMock(
            return_value={
                "id": DUENO_ID,
                "pin_hash": PIN_HASH,
                "password_hash": PASS_HASH,
                "activo": True,
            }
        ),
    )
    emitir = AsyncMock(return_value="token")
    monkeypatch.setattr(f"{SVC}._emitir_token_pin", emitir)
    conn = ConexionConTransaccion()

    with pytest.raises(PinInvalidoError):
        await turnos_caja_service.validar_pin_cajero(
            conn,  # type: ignore[arg-type]
            DUENO_ID,
            APERTURA_ID,
            "contraseña-larga",
        )

    otra = _usuario("Cajero")
    with pytest.raises(turnos_caja_service.TurnoAjenoError):
        await turnos_caja_service.validar_pin_cajero(
            conn,  # type: ignore[arg-type]
            otra.sub,
            APERTURA_ID,
            "4821",
            solicitante=otra,
        )

    resp = await turnos_caja_service.validar_pin_cajero(conn, DUENO_ID, APERTURA_ID, "4821")  # type: ignore[arg-type]
    assert resp["token_pin"] == "token"
    assert limite.tipos == ["cajero"]


# ── A15: cancelar el conteo de otra cajera ──────────────────────────────────


@pytest.fixture
def cancelar(monkeypatch: pytest.MonkeyPatch, permisos: None) -> dict[str, AsyncMock]:
    mocks = {
        "bloquear_apertura": AsyncMock(return_value=_apertura()),
        "resetear_conteo_apertura": AsyncMock(),
        "actualizar_estado_apertura": AsyncMock(),
        "obtener_turno_activo": AsyncMock(return_value=MagicMock()),
    }
    for nombre, mock in mocks.items():
        monkeypatch.setattr(f"{SVC}.{nombre}", mock)
    return mocks


async def test_cancelar_conteo_de_otra_cajera_responde_403(
    cancelar: dict[str, AsyncMock],
) -> None:
    otra = _usuario("Cajero")
    with pytest.raises(HTTPException) as exc:
        await turnos_caja_service.cancelar_conteo(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            otra.sub,
            APERTURA_ID,
            solicitante=otra,
        )
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "TURNO_AJENO"
    cancelar["resetear_conteo_apertura"].assert_not_called()


async def test_cancelar_conteo_sin_solicitante_solo_deja_al_dueno(
    cancelar: dict[str, AsyncMock],
) -> None:
    with pytest.raises(turnos_caja_service.TurnoAjenoError):
        await turnos_caja_service.cancelar_conteo(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            str(uuid4()),
            APERTURA_ID,
        )


async def test_cancelar_conteo_del_dueno_funciona(cancelar: dict[str, AsyncMock]) -> None:
    dueno = _usuario("Cajero", sub=DUENO_ID)
    await turnos_caja_service.cancelar_conteo(
        ConexionConTransaccion(),  # type: ignore[arg-type]
        dueno.sub,
        APERTURA_ID,
        solicitante=dueno,
    )
    cancelar["resetear_conteo_apertura"].assert_awaited_once()
    cancelar["obtener_turno_activo"].assert_awaited_once_with(
        cancelar["obtener_turno_activo"].await_args.args[0], DUENO_ID
    )


async def test_cancelar_conteo_admin_de_la_sucursal_puede(
    cancelar: dict[str, AsyncMock],
) -> None:
    admin = _usuario("Administrador", branch_id=SUC)
    await turnos_caja_service.cancelar_conteo(
        ConexionConTransaccion(),  # type: ignore[arg-type]
        admin.sub,
        APERTURA_ID,
        solicitante=admin,
    )
    cancelar["resetear_conteo_apertura"].assert_awaited_once()
    # Devuelve el turno del cajero dueño, no el del administrador.
    assert cancelar["obtener_turno_activo"].await_args.args[1] == DUENO_ID


async def test_cancelar_conteo_admin_de_otra_sucursal_responde_403(
    cancelar: dict[str, AsyncMock],
) -> None:
    admin = _usuario("Administrador", branch_id=OTRA_SUC)
    with pytest.raises(turnos_caja_service.TurnoAjenoError):
        await turnos_caja_service.cancelar_conteo(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            admin.sub,
            APERTURA_ID,
            solicitante=admin,
        )


# ── Permisos de los endpoints ───────────────────────────────────────────────


class _ConexionQueNoSeDebeUsar:
    def __getattr__(self, nombre: str) -> Any:
        raise AssertionError(f"El endpoint usó la conexión ({nombre}) sin validar el permiso")


@pytest.fixture
def cliente(permisos: None) -> Any:
    def _hacer(rol: str) -> TestClient:
        usuario = _usuario(rol)
        app.dependency_overrides[get_current_user] = lambda: usuario
        app.dependency_overrides[get_db] = lambda: _ConexionQueNoSeDebeUsar()
        return TestClient(app, raise_server_exceptions=False)

    try:
        yield _hacer
    finally:
        app.dependency_overrides.clear()


_ENDPOINTS_PIN = [
    ("/api/turnos-caja/validar-pin-cajero", {"turno_id": APERTURA_ID, "pin": "0000"}),
    (
        "/api/turnos-caja/validar-pin-admin",
        {"turno_id": APERTURA_ID, "admin_email": "a@b.c", "pin": "0000"},
    ),
    (
        "/api/turnos-caja/revision-admin",
        {"turno_id": APERTURA_ID, "admin_email": "a@b.c", "admin_password": "x"},
    ),
    ("/api/turnos-caja/confirmar", {"turno_id": APERTURA_ID}),
]


@pytest.mark.parametrize("rol", ["Cocina", "Inventario"])
@pytest.mark.parametrize(("ruta", "cuerpo"), _ENDPOINTS_PIN)
def test_roles_sin_caja_no_alcanzan_la_validacion_de_pin(
    cliente: Any, rol: str, ruta: str, cuerpo: dict[str, Any]
) -> None:
    resp = cliente(rol).post(ruta, json=cuerpo)
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(("ruta", "cuerpo"), _ENDPOINTS_PIN[:2])
def test_cajero_si_alcanza_la_validacion_de_pin(
    cliente: Any, monkeypatch: pytest.MonkeyPatch, ruta: str, cuerpo: dict[str, Any]
) -> None:
    ok = AsyncMock(return_value={"ok": True, "mensaje": "", "token_pin": "t"})
    monkeypatch.setattr(turnos_caja_service, "validar_pin_cajero", ok)
    monkeypatch.setattr(turnos_caja_service, "validar_pin_admin", ok)
    resp = cliente("Cajero").post(ruta, json=cuerpo)
    assert resp.status_code == 200
    assert "solicitante" in ok.await_args.kwargs
