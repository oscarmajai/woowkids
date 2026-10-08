"""El correo de los usuarios no distingue mayúsculas.

Pruebas con BD real: tests/db/test_usuarios_sesion_db.py.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import asyncpg
import pytest
from app.schemas.auth import TokenData
from app.schemas.user import UserCreateRequest, UserUpdateRequest
from app.services import user_service

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


# ── Correo normalizado ─────────────────────────────────────────────────────


def test_alta_y_edicion_normalizan_el_correo():
    alta = UserCreateRequest(email=" CAJERO1.Zapopan@WoowKids.com ", password="12345678", **_BASE)
    edicion = UserUpdateRequest(email="CAJERO1.Zapopan@WoowKids.com", **_BASE)
    assert alta.email == "cajero1.zapopan@woowkids.com"
    assert edicion.email == "cajero1.zapopan@woowkids.com"


def test_normalizar_email_del_repositorio():
    from app.repositories.user_repository import normalizar_email

    assert normalizar_email("  Cajero1.Zapopan@WoowKids.com ") == "cajero1.zapopan@woowkids.com"


@pytest.mark.asyncio
async def test_login_busca_el_correo_normalizado():
    from app.repositories import user_repository

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    await user_repository.get_usuario_by_email(conn, "Cajero1.Zapopan@WoowKids.com")
    sql, email = conn.fetchrow.await_args.args
    assert "lower(u.email) = $1" in sql
    assert email == "cajero1.zapopan@woowkids.com"


@pytest.mark.asyncio
async def test_email_exists_no_distingue_mayusculas_y_excluye_al_propio():
    from app.repositories import user_repository

    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    propio = uuid4()
    await user_repository.email_exists(conn, "A@B.com", excluir_id=propio)
    sql, email, excluir = conn.fetchrow.await_args.args
    assert "lower(email) = $1" in sql
    assert (email, excluir) == ("a@b.com", propio)


@pytest.mark.asyncio
async def test_update_user_excluye_al_propio_usuario_al_validar_el_correo():
    """Una cuenta vieja con mayúsculas se puede guardar ya normalizada sin 409."""
    conn = FakeConn()
    target = _usuario_record(email="Juan@Test.com")
    body = UserUpdateRequest(email="juan@test.com", branch_id=target["sucursal_id"], **_BASE)
    with (
        patch(
            "app.services.user_service.get_usuario_by_id",
            AsyncMock(side_effect=[target, target]),
        ),
        patch("app.services.user_service._assert_role_valid", AsyncMock()),
        patch(
            "app.services.user_service.email_exists", AsyncMock(return_value=False)
        ) as mock_existe,
        patch("app.services.user_service.update_usuario", AsyncMock(return_value=True)),
    ):
        await user_service.update_user(
            conn, target["id"], body, _token_data("AdministradorSistema")
        )
    mock_existe.assert_awaited_once_with(conn, "juan@test.com", excluir_id=target["id"])


@pytest.mark.asyncio
async def test_create_user_traduce_la_violacion_unica_del_correo_a_409():
    conn = FakeConn()
    body = UserCreateRequest(email="a@b.com", password="12345678", branch_id=uuid4(), **_BASE)
    violacion = asyncpg.UniqueViolationError("duplicado")
    violacion.constraint_name = "uq_usuarios_email_lower"  # type: ignore[attr-defined]
    with (
        patch("app.services.user_service._assert_role_valid", AsyncMock()),
        patch("app.services.user_service.email_exists", AsyncMock(return_value=False)),
        patch("app.services.user_service.create_usuario", AsyncMock(side_effect=violacion)),
        pytest.raises(user_service.EmailAlreadyExistsError),
    ):
        await user_service.create_user(conn, body, _token_data("AdministradorSistema"))
