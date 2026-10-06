"""Turno de caja: turno activo opcional, retiros e ingresos. Sin BD.

- GET /turnos-caja/activo?opcional=true responde null en vez de 404.
- El rechazo de un retiro dice cuánto hay disponible.
- El ingreso de efectivo guarda su motivo."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.api.routers import turnos_caja as turnos_router
from app.schemas.auth import TokenData
from app.schemas.caja import IngresoEfectivoCreate
from app.services import turnos_caja_service as svc
from fastapi import HTTPException

from tests.unit.pin_fakes import ConexionConTransaccion

SVC = "app.services.turnos_caja_service"


def _token(role: str) -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="x@test.com",
        role=role,
        branch_id=uuid4(),
        permissions=[],
        jti="jti",
        exp=datetime(2099, 1, 1, tzinfo=UTC),
    )


# ── Turno activo opcional ────────────────────────────────────────────────────


async def test_turno_activo_opcional_responde_null_sin_turno() -> None:
    with patch(f"{SVC}.obtener_turno_activo", AsyncMock(side_effect=svc.TurnoNoEncontradoError())):
        resultado = await turnos_router.obtener_activo(
            sucursal_id=None,
            opcional=True,
            current_user=_token("Cajero"),
            conn=object(),  # type: ignore[arg-type]
        )
    assert resultado is None


async def test_turno_activo_sin_opcional_sigue_respondiendo_404() -> None:
    with (
        patch(f"{SVC}.obtener_turno_activo", AsyncMock(side_effect=svc.TurnoNoEncontradoError())),
        pytest.raises(HTTPException) as exc_info,
    ):
        await turnos_router.obtener_activo(
            sucursal_id=None,
            opcional=False,
            current_user=_token("Cajero"),
            conn=object(),  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 404


# ── El mensaje del retiro rechazado dice cuánto hay ──────────────────────────


def test_efectivo_insuficiente_dice_el_disponible_con_formato() -> None:
    error = svc.EfectivoInsuficienteError(Decimal("10315.00"))
    assert error.status_code == 409
    assert error.detail["code"] == "EFECTIVO_INSUFICIENTE"
    assert "$10,315.00" in error.detail["message"]
    assert error.detail["disponible"] == 10315.0


# ── UX: motivo del ingreso de efectivo ───────────────────────────────────────


async def test_ingreso_de_efectivo_guarda_el_motivo() -> None:
    user_id = str(uuid4())
    apertura_id = str(uuid4())
    registrar = AsyncMock(
        return_value={
            "id": 1,
            "apertura_caja_id": apertura_id,
            "monto": Decimal("200"),
            "observaciones": "Cambio para el fin de semana",
            "creado": datetime(2026, 10, 3, 12, tzinfo=UTC),
        }
    )
    with (
        patch(
            f"{SVC}.bloquear_apertura",
            AsyncMock(return_value={"cajero_id": user_id, "estado": "ABIERTA"}),
        ),
        patch(f"{SVC}.registrar_ingreso_efectivo", registrar),
    ):
        resp = await svc.crear_ingreso(
            ConexionConTransaccion(),  # type: ignore[arg-type]
            user_id,
            IngresoEfectivoCreate(
                apertura_caja_id=apertura_id,
                monto=Decimal("200"),
                observaciones=" Cambio para el fin de semana ",
            ),
        )

    assert registrar.call_args.kwargs["observaciones"] == "Cambio para el fin de semana"
    assert resp.observaciones == "Cambio para el fin de semana"
