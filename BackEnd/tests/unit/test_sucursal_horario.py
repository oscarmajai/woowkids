"""La cajera no conocía el horario de su sucursal.

`GET /api/sucursales/{id}` exige `sucursales:ver` (el Cajero no lo tiene), así
que el calendario y Nueva reservación recibían 403 y pintaban 09:00-20:00 en
lugar del horario real. `GET /api/sucursales/{id}/horario` da solo los datos
operativos a quien gestiona reservaciones, y solo de su propia sucursal.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.api.deps import get_current_user
from app.core.database import get_db
from app.main import app
from app.schemas.auth import TokenData
from app.services import branch_service, permission_service
from fastapi.testclient import TestClient

PROPIA = UUID("aaaaaaaa-0000-0000-0000-00000000000a")
OTRA = UUID("bbbbbbbb-0000-0000-0000-00000000000b")
PERMISOS_CAJERO = frozenset({"reservaciones:ver", "reservaciones:listar"})


def _usuario(rol: str) -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="cajera@woowkids.test",
        role=rol,
        branch_id=PROPIA,
        jti=str(uuid4()),
        exp=datetime.now(tz=UTC) + timedelta(hours=1),
    )


@pytest.fixture
def cliente(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setitem(permission_service._cache, "Cajero", PERMISOS_CAJERO)
    monkeypatch.setitem(permission_service._cache, "Cocina", frozenset())

    async def datos(_conn: Any, sucursal_id: UUID) -> dict[str, Any]:
        return {
            "id": sucursal_id,
            "nombre": "Woow Kids Zapopan Plaza Patria",
            "zona_horaria": "America/Mexico_City",
            "hora_apertura": time(10, 0),
            "hora_cierre": time(21, 30),
        }

    monkeypatch.setattr(branch_service, "get_datos_operativos", datos)
    app.dependency_overrides[get_db] = lambda: object()

    def con_rol(rol: str) -> TestClient:
        app.dependency_overrides[get_current_user] = lambda: _usuario(rol)
        return TestClient(app, raise_server_exceptions=False)

    try:
        yield con_rol
    finally:
        app.dependency_overrides.clear()


def test_cajera_lee_el_horario_de_su_sucursal(cliente: Any) -> None:
    resp = cliente("Cajero").get(f"/api/sucursales/{PROPIA}/horario")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "id": str(PROPIA),
        "nombre": "Woow Kids Zapopan Plaza Patria",
        "zona_horaria": "America/Mexico_City",
        "hora_apertura": "10:00:00",
        "hora_cierre": "21:30:00",
    }


def test_cajera_sigue_sin_ver_los_datos_administrativos(cliente: Any) -> None:
    assert cliente("Cajero").get(f"/api/sucursales/{PROPIA}").status_code == 403


def test_cajera_no_lee_el_horario_de_otra_sucursal(cliente: Any) -> None:
    resp = cliente("Cajero").get(f"/api/sucursales/{OTRA}/horario")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN_SUCURSAL"


def test_sin_permiso_de_reservaciones_da_403(cliente: Any) -> None:
    assert cliente("Cocina").get(f"/api/sucursales/{PROPIA}/horario").status_code == 403
