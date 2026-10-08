"""No se desactiva una caja con turno abierto (DELETE /cajas/{id} y
PATCH con activo=false responden 409). Sin BD; con PostgreSQL real en
tests/db/test_cajas_turno_abierto_pg.py."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.api.routers import cajas_admin
from app.schemas.auth import TokenData
from app.schemas.horarios_cajas import CajaAdminUpdate
from fastapi import HTTPException

from tests.unit.pin_fakes import ConexionConTransaccion

CAJAS = "app.api.routers.cajas_admin"
SUCURSAL = uuid4()


def _token(role: str = "Administrador") -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="x@test.com",
        role=role,
        branch_id=SUCURSAL,
        permissions=[],
        jti="jti",
        exp=datetime(2099, 1, 1, tzinfo=UTC),
    )


# ── Desactivar una caja con turno abierto ────────────────────────────────────


def _caja(**extra: Any) -> dict[str, Any]:
    base = {
        "id": str(uuid4()),
        "sucursal_id": str(SUCURSAL),
        "nombre": "Caja Patria 1",
        "numero": 1,
        "activo": True,
        "impresora": None,
        "turno_actual": None,
    }
    base.update(extra)
    return base


async def test_eliminar_caja_con_turno_abierto_responde_409() -> None:
    caja = _caja()
    eliminar = AsyncMock(return_value=True)
    with (
        patch(f"{CAJAS}.get_caja_admin_por_id", AsyncMock(return_value=caja)),
        patch(f"{CAJAS}.bloquear_caja", AsyncMock(return_value=True)),
        patch(f"{CAJAS}.caja_tiene_turno_activo", AsyncMock(return_value=True)),
        patch(f"{CAJAS}.eliminar_caja_admin", eliminar),
        pytest.raises(HTTPException) as exc_info,
    ):
        await cajas_admin.eliminar(caja["id"], _token(), ConexionConTransaccion())  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "CAJA_CON_TURNO_ABIERTO"
    eliminar.assert_not_called()


async def test_eliminar_caja_sin_turno_la_desactiva() -> None:
    caja = _caja()
    eliminar = AsyncMock(return_value=True)
    bloquear = AsyncMock(return_value=True)
    with (
        patch(f"{CAJAS}.get_caja_admin_por_id", AsyncMock(return_value=caja)),
        patch(f"{CAJAS}.bloquear_caja", bloquear),
        patch(f"{CAJAS}.caja_tiene_turno_activo", AsyncMock(return_value=False)),
        patch(f"{CAJAS}.eliminar_caja_admin", eliminar),
    ):
        await cajas_admin.eliminar(caja["id"], _token(), ConexionConTransaccion())  # type: ignore[arg-type]

    bloquear.assert_awaited_once()
    eliminar.assert_awaited_once()


async def test_editar_activo_false_con_turno_abierto_responde_409() -> None:
    caja = _caja()
    actualizar = AsyncMock()
    with (
        patch(f"{CAJAS}.get_caja_admin_por_id", AsyncMock(return_value=caja)),
        patch(f"{CAJAS}.bloquear_caja", AsyncMock(return_value=True)),
        patch(f"{CAJAS}.caja_tiene_turno_activo", AsyncMock(return_value=True)),
        patch(f"{CAJAS}.actualizar_caja_admin", actualizar),
        pytest.raises(HTTPException) as exc_info,
    ):
        await cajas_admin.editar(
            caja["id"],
            CajaAdminUpdate(activo=False),
            _token(),
            ConexionConTransaccion(),  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    actualizar.assert_not_called()


async def test_editar_nombre_con_turno_abierto_si_se_permite() -> None:
    caja = _caja(turno_actual={"id": "x", "cajero": "Diego", "apertura": None})
    actualizar = AsyncMock(return_value={**caja, "nombre": "Caja nueva", "turno_actual": None})
    revisar = AsyncMock(return_value=True)
    with (
        patch(f"{CAJAS}.get_caja_admin_por_id", AsyncMock(return_value=caja)),
        patch(f"{CAJAS}.caja_tiene_turno_activo", revisar),
        patch(f"{CAJAS}.actualizar_caja_admin", actualizar),
    ):
        await cajas_admin.editar(
            caja["id"],
            CajaAdminUpdate(nombre="Caja nueva"),
            _token(),
            ConexionConTransaccion(),  # type: ignore[arg-type]
        )

    revisar.assert_not_called()
    actualizar.assert_awaited_once()
