"""A10 — un usuario desactivado se lista (filtro `estado`) y se puede reactivar.

Pruebas con BD real: tests/db/test_usuarios_sesion_db.py.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.schemas.auth import TokenData
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


# ── A10: listado por estado y reactivación ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("estado", "activo"), [("activos", True), ("inactivos", False), ("todos", None)]
)
async def test_list_users_pasa_el_estado_al_repositorio(estado, activo):
    conn = FakeConn()
    branch_id = uuid4()
    with (
        patch(
            "app.services.user_service.get_usuarios_by_branch", AsyncMock(return_value=[])
        ) as por_sucursal,
        patch("app.services.user_service.get_all_usuarios", AsyncMock(return_value=[])) as todos,
    ):
        await user_service.list_users(conn, _token_data("Administrador", branch_id), estado)
        await user_service.list_users(conn, _token_data("AdministradorSistema"), estado)
    por_sucursal.assert_awaited_once_with(conn, branch_id, activo)
    todos.assert_awaited_once_with(conn, activo)


@pytest.mark.asyncio
async def test_list_users_por_defecto_solo_activos():
    conn = FakeConn()
    with patch("app.services.user_service.get_all_usuarios", AsyncMock(return_value=[])) as todos:
        await user_service.list_users(conn, _token_data("AdministradorSistema"))
    todos.assert_awaited_once_with(conn, True)


@pytest.mark.asyncio
async def test_update_usuario_no_exige_que_el_usuario_este_activo():
    from app.repositories import user_repository

    conn = MagicMock()
    conn.execute = AsyncMock(return_value="UPDATE 1")
    await user_repository.update_usuario(
        conn,
        user_id=uuid4(),
        email="a@b.com",
        nombre_completo="Juan",
        rol=ROL_CAJERO,
        password_hash=None,
        modificado_por=uuid4(),
        activo=True,
    )
    sql = conn.execute.await_args.args[0]
    assert "activo = TRUE" not in sql.split("WHERE", 1)[1]
