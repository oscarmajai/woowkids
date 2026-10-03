"""C1 #2 / A5 / A16 / B15 / N2: abrir turno exige el PIN del cajero.

- Sin PIN configurado vale la contraseña; con PIN, SOLO el PIN (A16).
- Un PIN mal escrito responde 403 PIN_INVALIDO, nunca 401 (A5: el front
  trataba el 401 como sesión vencida y cerraba la sesión).
- El PIN se valida aunque ya haya un turno abierto, y un turno abierto con
  otra caja/fondo responde 409 en vez de 201 con el existente (B15).
- Dos aperturas simultáneas ya no dan 500 por el índice único (N2).
"""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest
from app.core.security import hash_password
from app.schemas.caja import AbrirTurnoPayload
from app.services import turnos_caja_service
from fastapi import HTTPException

from tests.unit.pin_fakes import ConexionConTransaccion, LimiteEnMemoria

SVC = "app.services.turnos_caja_service"
CAJERO_ID = str(uuid4())
SUCURSAL_ID = str(uuid4())
CAJA_ID = str(uuid4())
TURNO_ID = str(uuid4())


def _cajero_row(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": CAJERO_ID,
        "email": "cajero@test.com",
        "password_hash": hash_password("contraseña123"),
        "pin_hash": None,
        "nombre_completo": "Cajero Uno",
        "apellidos": None,
        "telefono": None,
        "rol": "Cajero",
        "sucursal_id": SUCURSAL_ID,
        "activo": True,
        "ultimo_acceso": None,
    }
    base.update(overrides)
    return base


def _payload(**overrides: Any) -> AbrirTurnoPayload:
    datos: dict[str, Any] = {
        "fondo_inicial": Decimal("500.00"),
        "sucursal_id": SUCURSAL_ID,
        "terminal": "CAJA 01",
        "turno_id": TURNO_ID,
        "pin": "1234",
    }
    datos.update(overrides)
    return AbrirTurnoPayload(**datos)


def _activa(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": str(uuid4()),
        "caja_id": CAJA_ID,
        "turno_id": TURNO_ID,
        "fondo_inicial": Decimal("500.00"),
        "sucursal_id": SUCURSAL_ID,
        "sucursal_nombre": "Plaza Patria",
        "terminal": "CAJA 01",
    }
    base.update(overrides)
    return base


@pytest.fixture
def limite(monkeypatch: pytest.MonkeyPatch) -> LimiteEnMemoria:
    return LimiteEnMemoria().instalar(monkeypatch)


@pytest.fixture
def entorno(monkeypatch: pytest.MonkeyPatch, limite: LimiteEnMemoria) -> dict[str, AsyncMock]:
    """Cajero con PIN 1234, caja existente y libre, sin turno activo."""
    mocks = {
        "get_usuario_by_id": AsyncMock(return_value=_cajero_row(pin_hash=hash_password("1234"))),
        "get_caja_por_codigo": AsyncMock(return_value={"id": CAJA_ID}),
        "get_caja_por_id": AsyncMock(return_value={"id": CAJA_ID}),
        "get_apertura_activa_por_usuario": AsyncMock(return_value=None),
        "get_apertura_activa_por_caja": AsyncMock(return_value=None),
        "turno_disponible_en_sucursal": AsyncMock(return_value=True),
        "crear_apertura_caja": AsyncMock(
            return_value={
                "id": uuid4(),
                "sucursal_id": SUCURSAL_ID,
                "sucursal_nombre": "Plaza Patria",
                "cajero_id": CAJERO_ID,
                "cajero_nombre": "Cajero Uno",
                "terminal": "CAJA 01",
                "fondo_inicial": Decimal("500.00"),
                "fecha_apertura": "2026-10-03T08:00:00",
            }
        ),
        "obtener_turno_activo": AsyncMock(return_value=MagicMock(name="turno_existente")),
    }
    for nombre, mock in mocks.items():
        monkeypatch.setattr(f"{SVC}.{nombre}", mock)
    return mocks


async def _abrir(payload: AbrirTurnoPayload) -> Any:
    return await turnos_caja_service.abrir_turno(
        ConexionConTransaccion(),  # type: ignore[arg-type]
        CAJERO_ID,
        None,
        payload,
    )


async def test_abrir_turno_sin_pin_lanza_422(entorno: dict[str, AsyncMock]) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload(pin=None))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "PIN_REQUERIDO"


async def test_abrir_turno_con_pin_incorrecto_lanza_403_no_401(
    entorno: dict[str, AsyncMock], limite: LimiteEnMemoria
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload(pin="0000"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "PIN_INVALIDO"
    assert limite.total() == 1
    entorno["crear_apertura_caja"].assert_not_called()


async def test_abrir_turno_sin_pin_configurado_acepta_password(
    entorno: dict[str, AsyncMock],
) -> None:
    entorno["get_usuario_by_id"].return_value = _cajero_row(pin_hash=None)

    await _abrir(_payload(pin="contraseña123"))

    entorno["crear_apertura_caja"].assert_awaited_once()


async def test_abrir_turno_con_pin_configurado_rechaza_la_password(
    entorno: dict[str, AsyncMock],
) -> None:
    """A16: si el cajero ya tiene PIN, su contraseña no sirve como PIN."""
    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload(pin="contraseña123"))

    assert exc_info.value.status_code == 403
    entorno["crear_apertura_caja"].assert_not_called()


async def test_abrir_turno_bloquea_tras_cinco_fallos(
    entorno: dict[str, AsyncMock], limite: LimiteEnMemoria
) -> None:
    for _ in range(5):
        with pytest.raises(HTTPException) as exc_info:
            await _abrir(_payload(pin="0000"))
        assert exc_info.value.status_code == 403

    # Bloqueado: ni el PIN correcto pasa hasta que venza la ventana.
    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload(pin="1234"))
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "PIN_BLOQUEADO"
    entorno["crear_apertura_caja"].assert_not_called()


async def test_abrir_turno_con_turno_abierto_valida_el_pin_primero(
    entorno: dict[str, AsyncMock],
) -> None:
    """B15: antes devolvía 201 con el turno existente sin mirar el PIN."""
    entorno["get_apertura_activa_por_usuario"].return_value = _activa()

    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload(pin="0000"))

    assert exc_info.value.status_code == 403
    entorno["obtener_turno_activo"].assert_not_called()


async def test_abrir_turno_con_turno_abierto_en_otra_caja_responde_409(
    entorno: dict[str, AsyncMock],
) -> None:
    entorno["get_apertura_activa_por_usuario"].return_value = _activa(
        caja_id=str(uuid4()), terminal="CAJA 01"
    )

    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload(terminal="CAJA 02"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "TURNO_YA_ABIERTO"
    assert "CAJA 01" in exc_info.value.detail["message"]
    entorno["crear_apertura_caja"].assert_not_called()


async def test_abrir_turno_con_turno_abierto_y_otro_fondo_responde_409(
    entorno: dict[str, AsyncMock],
) -> None:
    entorno["get_apertura_activa_por_usuario"].return_value = _activa(
        fondo_inicial=Decimal("1000.00")
    )

    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload())

    assert exc_info.value.status_code == 409


async def test_abrir_turno_repetido_devuelve_el_existente(
    entorno: dict[str, AsyncMock],
) -> None:
    """Reintento de la misma apertura (timeout, doble clic): con PIN válido y los
    mismos datos se devuelve el turno ya abierto en vez de un error."""
    entorno["get_apertura_activa_por_usuario"].return_value = _activa()

    resultado = await _abrir(_payload())

    assert resultado is entorno["obtener_turno_activo"].return_value
    entorno["crear_apertura_caja"].assert_not_called()


async def test_abrir_turno_en_otra_sucursal_responde_409(
    entorno: dict[str, AsyncMock],
) -> None:
    entorno["get_apertura_activa_por_usuario"].return_value = _activa(sucursal_id=str(uuid4()))

    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload())

    assert exc_info.value.detail["code"] == "TURNO_ACTIVO_OTRA_SUCURSAL"


def _violacion(constraint: str) -> asyncpg.UniqueViolationError:
    exc = asyncpg.UniqueViolationError("duplicate key")
    exc.constraint_name = constraint  # type: ignore[attr-defined]
    return exc


async def test_abrir_turno_carrera_del_mismo_cajero_responde_409_no_500(
    entorno: dict[str, AsyncMock],
) -> None:
    """N2: la otra petición ganó con otra caja → 409, no UniqueViolationError."""
    entorno["crear_apertura_caja"].side_effect = _violacion("uq_apertura_cajero_activo")
    entorno["get_apertura_activa_por_usuario"].side_effect = [
        None,
        _activa(caja_id=str(uuid4()), terminal="CAJA 02"),
    ]

    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "TURNO_YA_ABIERTO"


async def test_abrir_turno_carrera_identica_devuelve_el_ganador(
    entorno: dict[str, AsyncMock],
) -> None:
    entorno["crear_apertura_caja"].side_effect = _violacion("uq_apertura_cajero_activo")
    entorno["get_apertura_activa_por_usuario"].side_effect = [None, _activa()]

    resultado = await _abrir(_payload())

    assert resultado is entorno["obtener_turno_activo"].return_value


async def test_abrir_turno_carrera_por_la_misma_caja_responde_409(
    entorno: dict[str, AsyncMock],
) -> None:
    entorno["crear_apertura_caja"].side_effect = _violacion("uq_apertura_caja_activa")

    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "CAJA_OCUPADA"


async def test_abrir_turno_sin_sucursal_no_valida_pin(entorno: dict[str, AsyncMock]) -> None:
    with patch(f"{SVC}.pin_caja_service.verificar_con_limite") as verificar:
        with pytest.raises(HTTPException) as exc_info:
            await _abrir(_payload(sucursal_id=None))
    assert exc_info.value.detail["code"] == "SUCURSAL_REQUERIDA"
    verificar.assert_not_called()


async def test_abrir_turno_carrera_identica_por_la_caja_devuelve_el_ganador(
    entorno: dict[str, AsyncMock],
) -> None:
    """Doble clic: la otra petición del mismo cajero ganó la caja entre las
    lecturas (o saltó primero el índice de la caja); no es CAJA_OCUPADA."""
    entorno["crear_apertura_caja"].side_effect = _violacion("uq_apertura_caja_activa")
    entorno["get_apertura_activa_por_usuario"].side_effect = [None, _activa()]

    resultado = await _abrir(_payload())

    assert resultado is entorno["obtener_turno_activo"].return_value


async def test_abrir_turno_caja_ocupada_por_el_mismo_cajero_devuelve_el_existente(
    entorno: dict[str, AsyncMock],
) -> None:
    entorno["get_apertura_activa_por_caja"].return_value = {"id": uuid4()}
    entorno["get_apertura_activa_por_usuario"].side_effect = [None, _activa()]

    resultado = await _abrir(_payload())

    assert resultado is entorno["obtener_turno_activo"].return_value
    entorno["crear_apertura_caja"].assert_not_called()


async def test_abrir_turno_caja_ocupada_por_otro_cajero_responde_409(
    entorno: dict[str, AsyncMock],
) -> None:
    entorno["get_apertura_activa_por_caja"].return_value = {"id": uuid4()}

    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload())

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "CAJA_OCUPADA"


async def test_abrir_turno_con_horario_de_otra_sucursal_da_422(
    entorno: dict[str, AsyncMock], monkeypatch: pytest.MonkeyPatch
) -> None:
    """M19: el horario debe ser global o de la sucursal; antes se aceptaba el
    de cualquier sucursal (y uno inexistente daba 500 por la FK)."""
    disponible = AsyncMock(return_value=False)
    monkeypatch.setattr(f"{SVC}.turno_disponible_en_sucursal", disponible)

    with pytest.raises(HTTPException) as exc_info:
        await _abrir(_payload())

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "TURNO_INVALIDO"
    assert disponible.await_args is not None
    assert disponible.await_args.args[1:] == (TURNO_ID, SUCURSAL_ID)
    entorno["crear_apertura_caja"].assert_not_called()
