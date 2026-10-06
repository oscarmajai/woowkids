"""El cajero necesita canjear puntos desde la caja, pero GET
/lealtad/configuracion exige lealtad:gestionar_configuracion.

GET /lealtad/configuracion/canje expone, en solo lectura, el valor del punto
y el mínimo de canje de la sucursal de la sesión a quien tiene
lealtad:redimir. La configuración completa y su edición siguen protegidas.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.schemas.auth import TokenData
from app.services import lealtad_service, permission_service
from fastapi import HTTPException
from fastapi.testclient import TestClient

SUC_PROPIA = UUID("aaaaaaaa-0000-0000-0000-0000000000a6")
SUC_OTRA = UUID("bbbbbbbb-0000-0000-0000-0000000000a6")
ROL_CAJA = "CajeroPruebaA6"

# Mismos permisos de lealtad que el rol Cajero sembrado en 029_permisos_lealtad.
PERMISOS_CAJA = frozenset({"lealtad:ver_saldo", "lealtad:redimir"})


def _usuario(rol: str = ROL_CAJA, branch_id: UUID | None = SUC_PROPIA) -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="cajero.lealtad@woowkids.test",
        role=rol,
        branch_id=branch_id,
        permissions=[],
        jti=str(uuid4()),
        exp=datetime.now(tz=UTC) + timedelta(hours=1),
    )


def _config(sucursal_id: UUID = SUC_PROPIA) -> dict[str, Any]:
    return {
        "sucursal_id": sucursal_id,
        "porcentaje_retorno": 5.0,
        "dias_caducidad": 30,
        "valor_punto": 1.0,
        "activo": True,
        "otorga_puntos_comandas": True,
        "otorga_puntos_reservaciones": True,
        "otorga_puntos_checkin": True,
        "minimo_canje": 50,
        "creado": datetime.now(tz=UTC),
        "creado_por": None,
        "modificado": None,
        "modificado_por": None,
    }


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    mock = AsyncMock(return_value=_config())
    monkeypatch.setattr(lealtad_service.lealtad_repository, "obtener_configuracion", mock)
    return mock


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, repo: AsyncMock) -> Iterator[TestClient]:
    monkeypatch.setitem(permission_service._cache, ROL_CAJA, PERMISOS_CAJA)
    app.dependency_overrides[get_current_user] = lambda: _usuario()
    app.dependency_overrides[get_db] = lambda: object()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def test_cajero_lee_valor_punto_y_minimo_de_su_sucursal(
    client: TestClient, repo: AsyncMock
) -> None:
    resp = client.get("/api/lealtad/configuracion/canje")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "sucursal_id": str(SUC_PROPIA),
        "activo": True,
        "valor_punto": 1.0,
        "minimo_canje": 50,
    }
    # Se consulta la sucursal de la sesión, no otra.
    assert repo.await_args.args[1] == SUC_PROPIA


def test_cajero_con_su_propia_sucursal_explicita_pasa(client: TestClient) -> None:
    resp = client.get(f"/api/lealtad/configuracion/canje?sucursal_id={SUC_PROPIA}")
    assert resp.status_code == 200, resp.text


def test_cajero_no_lee_la_de_otra_sucursal(client: TestClient, repo: AsyncMock) -> None:
    resp = client.get(f"/api/lealtad/configuracion/canje?sucursal_id={SUC_OTRA}")
    assert resp.status_code == 403
    assert "FORBIDDEN_SUCURSAL" in resp.text
    repo.assert_not_awaited()


def test_la_respuesta_no_expone_porcentaje_ni_auditoria(client: TestClient) -> None:
    datos = client.get("/api/lealtad/configuracion/canje").json()
    for campo in ("porcentaje_retorno", "dias_caducidad", "creado_por", "modificado_por"):
        assert campo not in datos


def test_cajero_sigue_sin_ver_ni_editar_la_configuracion_completa(client: TestClient) -> None:
    assert client.get("/api/lealtad/configuracion").status_code == 403
    body = {"porcentaje_retorno": 99, "dias_caducidad": 1, "valor_punto": 100}
    assert client.put("/api/lealtad/configuracion", json=body).status_code == 403


def test_sin_permiso_de_canje_da_403(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(permission_service._cache, ROL_CAJA, frozenset({"lealtad:ver_saldo"}))
    assert client.get("/api/lealtad/configuracion/canje").status_code == 403


def test_sucursal_sin_configuracion_da_404(client: TestClient, repo: AsyncMock) -> None:
    repo.return_value = None
    assert client.get("/api/lealtad/configuracion/canje").status_code == 404


async def test_servicio_sistema_sin_sucursal_da_422(repo: AsyncMock) -> None:
    with pytest.raises(HTTPException) as exc:
        await lealtad_service.obtener_configuracion_canje(
            AsyncMock(), _usuario("AdministradorSistema", None), None
        )
    assert exc.value.status_code == 422
    repo.assert_not_awaited()
