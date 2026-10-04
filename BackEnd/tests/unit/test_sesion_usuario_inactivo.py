"""A11 — el token y el refresh token de un usuario desactivado o eliminado
ya no sirven.

Pruebas con BD real: tests/db/test_usuarios_sesion_db.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.api import deps
from app.core.roles import ROL_PADRE
from app.core.security import create_access_token
from app.schemas.auth import TokenData
from app.schemas.user import UserUpdateRequest
from app.services import auth_service, user_service
from fastapi import HTTPException

ROL_CAJERO = "Cajero"


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def transaction(self):
        return _FakeTransaction()


def _token_data(role: str, branch_id=None) -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="admin@test.com",
        role=role,
        branch_id=branch_id,
        permissions=[],
        jti="jti",
        exp=datetime(2099, 1, 1, tzinfo=UTC),
    )


def _usuario_record(**overrides):
    base = {
        "id": uuid4(),
        "email": "u@test.com",
        "password_hash": "hash",
        "pin_hash": None,
        "nombre_completo": "Juan",
        "apellidos": None,
        "telefono": None,
        "rol": ROL_CAJERO,
        "sucursal_id": uuid4(),
        "activo": True,
        "ultimo_acceso": None,
    }
    base.update(overrides)
    return base


_BASE = {"full_name": "Juan", "role": ROL_CAJERO}


# ── A11: token de usuario inactivo o inexistente ───────────────────────────


def _jwt(role: str = ROL_CAJERO, sub: str | None = None) -> str:
    return create_access_token(
        payload={
            "sub": sub or str(uuid4()),
            "email": "u@test.com",
            "role": role,
            "branch_id": str(uuid4()),
            "permissions": [],
        },
        expires_delta=timedelta(minutes=5),
    )


@pytest.mark.asyncio
async def test_token_de_usuario_inactivo_responde_401():
    with patch.object(deps, "get_estado_sesion", AsyncMock(return_value=(False, False, False))):
        with pytest.raises(HTTPException) as exc:
            await deps._resolve_token_data(_jwt(), MagicMock())
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "ACCOUNT_DISABLED"


@pytest.mark.asyncio
async def test_token_revocado_responde_401_invalid_token():
    with patch.object(deps, "get_estado_sesion", AsyncMock(return_value=(True, True, False))):
        with pytest.raises(HTTPException) as exc:
            await deps._resolve_token_data(_jwt(), MagicMock())
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "INVALID_TOKEN"


@pytest.mark.asyncio
async def test_token_de_usuario_activo_pasa_y_consulta_por_su_id():
    sub = str(uuid4())
    with patch.object(
        deps, "get_estado_sesion", AsyncMock(return_value=(False, True, False))
    ) as mock_estado:
        data = await deps._resolve_token_data(_jwt(sub=sub), MagicMock())
    assert data.sub == sub
    assert str(mock_estado.await_args.args[2]) == sub


@pytest.mark.asyncio
async def test_sesion_de_padre_no_se_busca_como_usuario():
    """El sub del token del portal de padres es el registro, no un usuario."""
    with patch.object(
        deps, "get_estado_sesion", AsyncMock(return_value=(False, True, False))
    ) as mock_estado:
        await deps._resolve_token_data(_jwt(role=ROL_PADRE), MagicMock())
    assert mock_estado.await_args.args[2] is None


@pytest.mark.asyncio
async def test_estado_sesion_en_una_sola_consulta():
    from app.repositories.token_repository import get_estado_sesion

    conn = MagicMock()
    conn.fetchrow = AsyncMock(
        return_value={"revocado": False, "usuario_activo": False, "debe_cambiar_password": False}
    )
    usuario_id = uuid4()
    resultado = await get_estado_sesion(conn, str(uuid4()), usuario_id)
    assert resultado == (False, False, False)
    conn.fetchrow.assert_awaited_once()
    sql = conn.fetchrow.await_args.args[0]
    assert "tokens_revocados" in sql and "activo = TRUE" in sql


@pytest.mark.asyncio
async def test_refresh_de_usuario_inactivo_se_rechaza():
    registro = {
        "usuario_id": uuid4(),
        "revocado": False,
        "expires_at": datetime.now(UTC) + timedelta(days=1),
        "sucursal_id": None,
    }
    with (
        patch.object(auth_service, "get_refresh_token", AsyncMock(return_value=registro)),
        patch.object(auth_service, "revoke_refresh_token", AsyncMock()),
        patch.object(
            auth_service,
            "get_usuario_by_id",
            AsyncMock(return_value=_usuario_record(activo=False)),
        ),
        pytest.raises(auth_service.InvalidRefreshTokenError),
    ):
        await auth_service.refresh_access_token(MagicMock(), "token-crudo")


@pytest.mark.asyncio
async def test_reactivar_no_revoca_sesiones():
    conn = FakeConn()
    target = _usuario_record(activo=False)
    body = UserUpdateRequest(
        email=target["email"], branch_id=target["sucursal_id"], is_active=True, **_BASE
    )
    with (
        patch(
            "app.services.user_service.get_usuario_by_id",
            AsyncMock(side_effect=[target, {**target, "activo": True}]),
        ),
        patch("app.services.user_service._assert_role_valid", AsyncMock()),
        patch("app.services.user_service.email_exists", AsyncMock(return_value=False)),
        patch(
            "app.services.user_service.update_usuario", AsyncMock(return_value=True)
        ) as mock_update,
        patch(
            "app.services.user_service.revoke_all_user_refresh_tokens", AsyncMock()
        ) as mock_revocar,
    ):
        result = await user_service.update_user(
            conn, target["id"], body, _token_data("AdministradorSistema")
        )
    assert mock_update.await_args.kwargs["activo"] is True
    assert result.is_active is True
    mock_revocar.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_user_revoca_refresh_tokens():
    conn = FakeConn()
    target = _usuario_record()
    with (
        patch("app.services.user_service.get_usuario_by_id", AsyncMock(return_value=target)),
        patch("app.services.user_service.delete_usuario", AsyncMock(return_value=True)),
        patch(
            "app.services.user_service.revoke_all_user_refresh_tokens", AsyncMock()
        ) as mock_revocar,
    ):
        await user_service.delete_user(conn, target["id"], _token_data("AdministradorSistema"))
    mock_revocar.assert_awaited_once_with(conn, target["id"])
