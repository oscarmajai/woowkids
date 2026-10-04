"""Bloqueante de entrega: SECRET_KEY y contraseña del administrador de fábrica.

- La API no arranca con la SECRET_KEY de fábrica (el entrypoint la reemplaza
  por una aleatoria guardada en la BD).
- Quien entra con la contraseña de fábrica queda obligado a cambiarla: la API
  solo le deja /auth/me, /auth/logout y PUT /usuarios/me/password.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.api import deps
from app.core.config import SECRET_KEY_DE_FABRICA, Settings
from app.core.security import hash_password
from app.schemas.auth import TokenData
from app.schemas.user import CambiarMiPasswordRequest
from app.services import auth_service, user_service
from fastapi import HTTPException
from pydantic import ValidationError

_MINIMO = {"database_url": "postgresql://x", "minio_access_key": "a", "minio_secret_key": "b"}


@pytest.mark.parametrize("clave", [SECRET_KEY_DE_FABRICA, "", "   "])
def test_la_api_no_arranca_con_secret_key_de_fabrica_o_vacia(clave):
    with pytest.raises(ValidationError):
        Settings(secret_key=clave, **_MINIMO)


def test_la_api_arranca_con_una_secret_key_propia():
    assert Settings(secret_key="una-clave-propia", **_MINIMO).secret_key == "una-clave-propia"


def _usuario(password: str, **overrides):
    base = {
        "id": uuid4(),
        "email": "admin@woowkids.com",
        "password_hash": hash_password(password),
        "pin_hash": None,
        "debe_cambiar_password": False,
        "nombre_completo": "Administrador",
        "apellidos": None,
        "telefono": None,
        "rol": "AdministradorSistema",
        "sucursal_id": None,
        "activo": True,
        "ultimo_acceso": None,
    }
    base.update(overrides)
    return base


async def _login(usuario, password):
    marcar = AsyncMock()
    with (
        patch.object(auth_service, "get_usuario_by_email", AsyncMock(return_value=usuario)),
        patch.object(auth_service, "marcar_cambio_password", marcar),
        patch.object(auth_service, "create_refresh_token", AsyncMock()),
        patch.object(auth_service, "update_ultimo_acceso", AsyncMock()),
        patch.object(auth_service, "get_permissions", return_value=[]),
    ):
        resultado = await auth_service.login(
            MagicMock(), usuario["email"], password, sucursal_id=None, remember_me=False
        )
    return resultado, marcar


@pytest.mark.asyncio
async def test_entrar_con_la_contrasena_de_fabrica_obliga_a_cambiarla():
    usuario = _usuario("admin1234")
    resultado, marcar = await _login(usuario, "admin1234")

    assert resultado.user.debe_cambiar_password is True
    marcar.assert_awaited_once_with(marcar.await_args.args[0], usuario["id"])


@pytest.mark.asyncio
async def test_entrar_con_una_contrasena_propia_no_obliga_nada():
    resultado, marcar = await _login(_usuario("mi-clave-segura"), "mi-clave-segura")

    assert resultado.user.debe_cambiar_password is False
    marcar.assert_not_awaited()


@pytest.mark.asyncio
async def test_el_administrador_inicial_marcado_sigue_obligado():
    usuario = _usuario("otra-clave-1", debe_cambiar_password=True)
    resultado, marcar = await _login(usuario, "otra-clave-1")

    assert resultado.user.debe_cambiar_password is True
    marcar.assert_not_awaited()


def _token(debe_cambiar_password: bool) -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="admin@woowkids.com",
        role="AdministradorSistema",
        branch_id=None,
        permissions=[],
        jti=str(uuid4()),
        exp=datetime(2099, 1, 1, tzinfo=UTC),
        debe_cambiar_password=debe_cambiar_password,
    )


@pytest.mark.asyncio
async def test_con_cambio_pendiente_la_api_responde_403():
    with pytest.raises(HTTPException) as exc:
        await deps.get_current_user(_token(True))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "PASSWORD_CHANGE_REQUIRED"


@pytest.mark.asyncio
async def test_sin_cambio_pendiente_la_api_deja_pasar():
    token = _token(False)
    assert await deps.get_current_user(token) is token


def test_solo_lo_necesario_para_cambiarla_acepta_el_cambio_pendiente():
    from app.main import app

    permitidas = {
        ruta.path
        for ruta in app.routes
        if any(
            d.call is deps.get_current_user_con_cambio_pendiente
            for d in getattr(ruta, "dependant", MagicMock(dependencies=[])).dependencies
        )
    }
    assert permitidas == {"/api/auth/me", "/api/auth/logout", "/api/usuarios/me/password"}


def _target(password: str):
    return {"id": uuid4(), "activo": True, "password_hash": hash_password(password)}


@pytest.mark.asyncio
async def test_cambiar_mi_password_guarda_la_nueva():
    target = _target("admin1234")
    guardar = AsyncMock(return_value=True)
    with (
        patch.object(user_service, "get_usuario_by_id", AsyncMock(return_value=target)),
        patch.object(user_service, "cambiar_password_propia", guardar),
    ):
        await user_service.cambiar_mi_password(
            MagicMock(),
            target["id"],
            CambiarMiPasswordRequest(actual="admin1234", nueva="una-nueva-segura"),
        )
    guardar.assert_awaited_once()


@pytest.mark.asyncio
async def test_cambiar_mi_password_exige_la_actual():
    target = _target("admin1234")
    with (
        patch.object(user_service, "get_usuario_by_id", AsyncMock(return_value=target)),
        pytest.raises(user_service.CredencialActualInvalidaError),
    ):
        await user_service.cambiar_mi_password(
            MagicMock(),
            target["id"],
            CambiarMiPasswordRequest(actual="otra", nueva="una-nueva-segura"),
        )


@pytest.mark.parametrize("nueva", ["admin1234", "mi-clave-actual"])
@pytest.mark.asyncio
async def test_cambiar_mi_password_rechaza_la_de_fabrica_o_la_misma(nueva):
    actual = "mi-clave-actual"
    target = _target(actual)
    with (
        patch.object(user_service, "get_usuario_by_id", AsyncMock(return_value=target)),
        pytest.raises(user_service.PasswordNoPermitidaError),
    ):
        await user_service.cambiar_mi_password(
            MagicMock(), target["id"], CambiarMiPasswordRequest(actual=actual, nueva=nueva)
        )
