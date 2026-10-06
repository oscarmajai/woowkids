"""Pruebas unitarias de app.services.pulseras: con mocks del repository (sin
DB). Cubre asignada_a: el nombre del nino o tutor que tiene la
pulsera cuando esta en uso."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.exceptions import NoEncontrado
from app.services import pulseras as pulseras_service

SUCURSAL_ID = uuid4()


@pytest.mark.asyncio
async def test_listar_todas_expone_asignada_a_cuando_esta_en_uso():
    fila = {
        "id": uuid4(),
        "sucursal_id": SUCURSAL_ID,
        "pulsera_rfid": "RFID-1",
        "activo": True,
        "usada": True,
        "asignada_a": "Juan Pérez",
        "numero_lote": None,
        "creado": None,
        "creado_por": None,
        "modificado": None,
        "modificado_por": None,
    }
    with patch("app.repositories.pulseras.listar_todas", new=AsyncMock(return_value=[fila])):
        resultado = await pulseras_service.listar_todas(conn=None, sucursal_id=SUCURSAL_ID)

    assert len(resultado) == 1
    assert resultado[0].asignada_a == "Juan Pérez"


@pytest.mark.asyncio
async def test_listar_todas_asignada_a_nulo_cuando_esta_disponible():
    fila = {
        "id": uuid4(),
        "sucursal_id": SUCURSAL_ID,
        "pulsera_rfid": "RFID-2",
        "activo": True,
        "usada": False,
        "asignada_a": None,
        "numero_lote": None,
        "creado": None,
        "creado_por": None,
        "modificado": None,
        "modificado_por": None,
    }
    with patch("app.repositories.pulseras.listar_todas", new=AsyncMock(return_value=[fila])):
        resultado = await pulseras_service.listar_todas(conn=None, sucursal_id=SUCURSAL_ID)

    assert resultado[0].usada is False
    assert resultado[0].asignada_a is None


# ── Consulta por RFID para distinguir "no existe" de "ya está en uso" ──


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("activo", "usada", "estado"),
    [
        (True, False, "disponible"),
        (True, True, "usada"),
        (False, False, "inactiva"),
        # Usada pesa más que inactiva: el cajero necesita saber que ya se asignó.
        (False, True, "usada"),
    ],
)
async def test_buscar_por_rfid_resume_el_estado(activo, usada, estado):
    fila = {"id": uuid4(), "pulsera_rfid": "WK-0000001", "activo": activo, "usada": usada}
    with patch(
        "app.repositories.pulseras.buscar_por_rfid", new=AsyncMock(return_value=fila)
    ) as repo:
        resultado = await pulseras_service.buscar_por_rfid(
            conn=None, sucursal_id=SUCURSAL_ID, pulsera_rfid=" WK-0000001 "
        )

    repo.assert_awaited_once_with(None, SUCURSAL_ID, "WK-0000001")
    assert resultado.estado == estado
    assert resultado.pulseraRfid == "WK-0000001"
    assert resultado.usada is usada


@pytest.mark.asyncio
async def test_buscar_por_rfid_inexistente_responde_404():
    with (
        patch("app.repositories.pulseras.buscar_por_rfid", new=AsyncMock(return_value=None)),
        pytest.raises(NoEncontrado) as exc,
    ):
        await pulseras_service.buscar_por_rfid(
            conn=None, sucursal_id=SUCURSAL_ID, pulsera_rfid="WK-0000099"
        )

    assert exc.value.status_code == 404
