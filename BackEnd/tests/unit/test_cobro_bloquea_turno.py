"""El cobro vuelve a exigir el turno ABIERTA bajo un bloqueo compartido
de la apertura. Sin BD; la prueba de concurrencia real está en
tests/db/test_cobro_bloquea_turno_pg.py."""

from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.services import turnos_caja_service as svc
from fastapi import HTTPException

SVC = "app.services.turnos_caja_service"


# ── El cobro vuelve a validar el turno bajo bloqueo ──────────────────────────


@pytest.mark.parametrize("estado", ["EN_CORTE", "CERRADA"])
async def test_bloquear_turno_para_cobro_rechaza_un_turno_que_ya_no_esta_abierto(
    estado: str,
) -> None:
    with (
        patch(
            f"{SVC}.bloquear_apertura_para_cobro",
            AsyncMock(return_value={"id": "a", "estado": estado}),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await svc.bloquear_turno_para_cobro(object(), str(uuid4()))  # type: ignore[arg-type]

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "TURNO_NO_ABIERTO"


async def test_bloquear_turno_para_cobro_sin_apertura_rechaza() -> None:
    with (
        patch(f"{SVC}.bloquear_apertura_para_cobro", AsyncMock(return_value=None)),
        pytest.raises(svc.TurnoNoAbiertoError),
    ):
        await svc.bloquear_turno_para_cobro(object(), str(uuid4()))  # type: ignore[arg-type]


async def test_bloquear_turno_para_cobro_con_turno_abierto_pasa() -> None:
    bloquear = AsyncMock(return_value={"id": "a", "estado": "ABIERTA"})
    with patch(f"{SVC}.bloquear_apertura_para_cobro", bloquear):
        await svc.bloquear_turno_para_cobro(object(), "apertura-1")  # type: ignore[arg-type]
    bloquear.assert_awaited_once()
    assert bloquear.call_args.args[1] == "apertura-1"


async def test_bloquear_apertura_para_cobro_usa_for_share() -> None:
    from app.repositories import caja_repository

    class Conn:
        sql = ""

        async def fetchrow(self, sql: str, *_args: Any) -> None:
            Conn.sql = sql
            return None

    await caja_repository.bloquear_apertura_para_cobro(Conn(), str(uuid4()))  # type: ignore[arg-type]
    assert "FOR SHARE" in Conn.sql
