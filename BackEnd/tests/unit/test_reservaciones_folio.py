"""Unit test de app.services.reservaciones.crear(): asigna folio legible
(migración 053) antes de insertar."""

from datetime import date, time
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.repositories import paquetes_repository, reservaciones_repository
from app.schemas.reservaciones import ReservacionesCrear, ReservacionesOut
from app.services import reservaciones

SUCURSAL_ID = uuid4()


def _body() -> ReservacionesCrear:
    return ReservacionesCrear(
        sucursal_id=SUCURSAL_ID,
        tipo_evento_id=uuid4(),
        paquete_id=uuid4(),
        nombre_cliente="Cliente de prueba",
        telefono_cliente="5555555555",
        fecha_evento=date(2026, 1, 1),
        hora_inicio=time(10, 0),
        hora_fin=time(14, 0),
        numero_personas=5,
        precio_base=Decimal("500.00"),
        precio_total=Decimal("500.00"),
        anticipo=Decimal("0"),
    )


@pytest.mark.asyncio
async def test_crear_asigna_el_folio_antes_de_insertar(monkeypatch):
    monkeypatch.setattr(
        reservaciones_repository, "siguiente_folio", AsyncMock(return_value="R-0042")
    )
    # crear() recalcula el precio con el paquete y revisa el plazo:
    # paquete de $500 sin pulseras y evento lejano.
    monkeypatch.setattr(
        paquetes_repository,
        "obtener",
        AsyncMock(
            return_value={
                "id": uuid4(),
                "sucursal_id": SUCURSAL_ID,
                "nombre": "Básico",
                "activo": True,
                "min_invitados": 1,
                "max_invitados": 10,
                "precio_base": Decimal("500.00"),
                "precio_hora_pulsera": Decimal("0"),
                "anticipo_porcentaje": None,
            }
        ),
    )
    monkeypatch.setattr(
        reservaciones_repository, "hoy_en_sucursal", AsyncMock(return_value=date(2025, 12, 1))
    )

    capturado: dict = {}

    async def fake_crear(conn, data):
        capturado.update(data)
        return {
            **data,
            "id": uuid4(),
            "saldo_pendiente": data["precio_total"],
            "comanda_enviada": False,
            "activo": True,
            "creado": None,
            "creado_por": None,
            "modificado": None,
            "modificado_por": None,
        }

    monkeypatch.setattr(reservaciones_repository, "crear", fake_crear)
    # ReservacionesOut exige datetime en "creado"; se evita instanciar el
    # modelo completo y solo se valida que crear() le pasó el folio al
    # repository, que es lo que cubre este test.
    monkeypatch.setattr(
        ReservacionesOut, "model_validate", classmethod(lambda cls, row: row), raising=False
    )

    await reservaciones.crear(AsyncMock(), _body(), str(uuid4()))

    assert capturado["folio"] == "R-0042"
