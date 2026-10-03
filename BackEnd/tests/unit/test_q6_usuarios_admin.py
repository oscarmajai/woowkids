"""Q6 (UX de administración de usuarios): nadie se elimina a sí mismo, el
usuario trae las sucursales de un Administrador y la sucursal el correo de su
administrador (no solo el suyo)."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.schemas.auth import TokenData
from app.services import branch_service, user_service


def _token(role: str, sub: str | None = None, branch_id=None) -> TokenData:
    return TokenData(
        sub=sub or str(uuid4()),
        email="admin@test.com",
        role=role,
        branch_id=branch_id,
        permissions=[],
        jti="jti",
        exp=datetime(2099, 1, 1, tzinfo=UTC),
    )


def _usuario(**overrides):
    base = {
        "id": uuid4(),
        "email": "u@test.com",
        "password_hash": "hash",
        "pin_hash": None,
        "nombre_completo": "Sofía",
        "apellidos": None,
        "telefono": None,
        "rol": "Administrador",
        "sucursal_id": None,
        "activo": True,
        "ultimo_acceso": None,
    }
    base.update(overrides)
    return base


# ── Eliminarse a sí mismo ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_se_puede_eliminar_la_propia_cuenta():
    propio = uuid4()
    current_user = _token("Gerente", sub=str(propio), branch_id=uuid4())
    get_usuario = AsyncMock()
    borrar = AsyncMock()

    with (
        patch("app.services.user_service.get_usuario_by_id", get_usuario),
        patch("app.services.user_service.delete_usuario", borrar),
        pytest.raises(user_service.AutoEliminacionError),
    ):
        await user_service.delete_user(object(), propio, current_user)  # type: ignore[arg-type]

    borrar.assert_not_awaited()


@pytest.mark.asyncio
async def test_el_sysadmin_tampoco_puede_eliminarse():
    propio = uuid4()
    with pytest.raises(user_service.AutoEliminacionError):
        await user_service.delete_user(
            object(),  # type: ignore[arg-type]
            propio,
            _token("AdministradorSistema", sub=str(propio)),
        )


@pytest.mark.asyncio
async def test_el_usuario_de_sistema_sigue_protegido():
    sistema = _usuario(rol="AdministradorSistema", email="sistema@mercury.internal")
    with (
        patch("app.services.user_service.get_usuario_by_id", AsyncMock(return_value=sistema)),
        pytest.raises(user_service.InsufficientPermissionsError),
    ):
        await user_service.delete_user(
            object(),  # type: ignore[arg-type]
            sistema["id"],
            _token("AdministradorSistema"),
        )


def test_router_responde_409_al_eliminarse_a_si_mismo(monkeypatch: pytest.MonkeyPatch):
    from app.api.deps import get_current_user
    from app.core.database import get_db
    from app.main import app
    from app.services import permission_service
    from fastapi.testclient import TestClient

    propio = uuid4()
    token = _token("Gerente", sub=str(propio), branch_id=uuid4())
    monkeypatch.setitem(permission_service._cache, "Gerente", frozenset({"usuarios:eliminar"}))

    app.dependency_overrides[get_current_user] = lambda: token
    app.dependency_overrides[get_db] = lambda: object()
    try:
        resp = TestClient(app).delete(f"/api/usuarios/{propio}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "AUTO_ELIMINACION"


# ── Sucursales del Administrador en el listado ───────────────────────────────


def test_respuesta_de_usuario_incluye_sucursales_del_administrador():
    sucursal = uuid4()
    resp = user_service._to_response(_usuario(sucursales_ids=[sucursal]))  # type: ignore[arg-type]
    assert resp.branch_id is None
    assert resp.sucursales_ids == [sucursal]


def test_respuesta_de_usuario_sin_sucursales_es_lista_vacia():
    resp = user_service._to_response(_usuario())  # type: ignore[arg-type]
    assert resp.sucursales_ids == []


# ── Correo del administrador de la sucursal ──────────────────────────────────


def _sucursal(**overrides):
    base = {
        "id": uuid4(),
        "nombre": "Zapopan Plaza Patria",
        "direccion": None,
        "ciudad": None,
        "estado": None,
        "codigo_postal": None,
        "zona_horaria": "America/Mexico_City",
        "hora_apertura": datetime(2026, 1, 1, 10).time(),
        "hora_cierre": datetime(2026, 1, 1, 21).time(),
        "telefono": None,
        "correo": "plazapatria@woowkids.mx",
        "administrador_id": uuid4(),
        "administrador_name": "Sofía",
        "administrador_email": "admin.zapopan@woowkids.mx",
        "clave": "SUC-ZAP-PP",
        "activo": True,
        "creado": None,
        "creado_por": None,
        "creador_name": None,
        "modificado": None,
        "modificado_por": None,
        "modificador_name": None,
    }
    base.update(overrides)
    return base


def test_sucursal_expone_el_correo_del_administrador_aparte_del_suyo():
    resp = branch_service._to_response(_sucursal())  # type: ignore[arg-type]
    assert resp.administrador_email == "admin.zapopan@woowkids.mx"
    assert resp.correo == "plazapatria@woowkids.mx"
