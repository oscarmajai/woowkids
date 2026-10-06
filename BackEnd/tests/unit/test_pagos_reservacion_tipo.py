"""Unit tests de app.services.pagos_reservacion._resolver_tipo: distingue
anticipo / pago / liquidación (migración 054)."""

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.repositories import (
    metodos_pago_repository,
    pagos_reservacion_repository,
    reservaciones_repository,
)
from app.schemas.pagos_reservacion import PagosReservacionCreate
from app.services import pagos_reservacion
from fastapi import HTTPException

RESERVACION_ID = uuid4()


def _reservacion(precio_total: str) -> dict:
    return {"id": RESERVACION_ID, "precio_total": Decimal(precio_total)}


def _conn() -> MagicMock:
    """Conexión simulada con `transaction()` usable como `async with`."""
    conn = MagicMock()

    @asynccontextmanager
    async def transaccion() -> Any:
        yield

    conn.transaction = transaccion
    return conn


@pytest.mark.asyncio
async def test_respeta_tipo_solicitado_si_no_liquida(monkeypatch):
    monkeypatch.setattr(
        reservaciones_repository, "obtener", AsyncMock(return_value=_reservacion("1000.00"))
    )
    monkeypatch.setattr(
        pagos_reservacion_repository, "sumar_pagos", AsyncMock(return_value=Decimal("0"))
    )

    tipo = await pagos_reservacion._resolver_tipo(
        AsyncMock(), RESERVACION_ID, Decimal("300.00"), "anticipo"
    )

    assert tipo == "anticipo"


@pytest.mark.asyncio
async def test_default_a_pago_si_no_se_solicita_nada(monkeypatch):
    monkeypatch.setattr(
        reservaciones_repository, "obtener", AsyncMock(return_value=_reservacion("1000.00"))
    )
    monkeypatch.setattr(
        pagos_reservacion_repository, "sumar_pagos", AsyncMock(return_value=Decimal("300.00"))
    )

    tipo = await pagos_reservacion._resolver_tipo(
        AsyncMock(), RESERVACION_ID, Decimal("200.00"), None
    )

    assert tipo == "pago"


@pytest.mark.asyncio
async def test_fuerza_liquidacion_si_el_pago_deja_el_saldo_en_cero(monkeypatch):
    """Aun pidiendo 'anticipo' (p.ej. quien liquida el 100% desde
    NuevaReservacionPage.vue), el backend lo sobreescribe a 'liquidacion' si
    el saldo llega a 0 -- regla explícita del negocio."""
    monkeypatch.setattr(
        reservaciones_repository, "obtener", AsyncMock(return_value=_reservacion("1000.00"))
    )
    monkeypatch.setattr(
        pagos_reservacion_repository, "sumar_pagos", AsyncMock(return_value=Decimal("700.00"))
    )

    tipo = await pagos_reservacion._resolver_tipo(
        AsyncMock(), RESERVACION_ID, Decimal("300.00"), "anticipo"
    )

    assert tipo == "liquidacion"


@pytest.mark.asyncio
async def test_fuerza_liquidacion_tambien_en_sobrepago(monkeypatch):
    monkeypatch.setattr(
        reservaciones_repository, "obtener", AsyncMock(return_value=_reservacion("1000.00"))
    )
    monkeypatch.setattr(
        pagos_reservacion_repository, "sumar_pagos", AsyncMock(return_value=Decimal("700.00"))
    )

    tipo = await pagos_reservacion._resolver_tipo(
        AsyncMock(), RESERVACION_ID, Decimal("500.00"), "pago"
    )

    assert tipo == "liquidacion"


@pytest.mark.asyncio
async def test_sin_reservacion_respeta_lo_solicitado(monkeypatch):
    """Si la reservación no existe (no debería pasar en producción, crear()
    la valida antes), no se intenta calcular el saldo: se usa lo pedido."""
    monkeypatch.setattr(reservaciones_repository, "obtener", AsyncMock(return_value=None))

    tipo = await pagos_reservacion._resolver_tipo(
        AsyncMock(), UUID(int=0), Decimal("100.00"), "anticipo"
    )

    assert tipo == "anticipo"


@pytest.mark.asyncio
async def test_crear_rechaza_metodo_de_pago_inexistente(monkeypatch):
    """Antes llegaba al INSERT y la llave foránea respondía 500."""

    monkeypatch.setattr(
        reservaciones_repository,
        "obtener_para_actualizar",
        AsyncMock(return_value={**_reservacion("1000.00"), "saldo_pendiente": Decimal("1000.00")}),
    )
    monkeypatch.setattr(metodos_pago_repository, "existe", AsyncMock(return_value=False))
    insertar = AsyncMock()
    monkeypatch.setattr(pagos_reservacion_repository, "crear", insertar)

    body = PagosReservacionCreate(
        reservacion_id=RESERVACION_ID, metodo_pago_id=uuid4(), monto=Decimal("100.00")
    )
    with pytest.raises(HTTPException) as exc:
        await pagos_reservacion.crear(_conn(), body, uuid4(), str(uuid4()))

    assert exc.value.status_code == 422
    insertar.assert_not_awaited()


@pytest.mark.asyncio
async def test_crear_rechaza_reservacion_inexistente(monkeypatch):
    monkeypatch.setattr(
        reservaciones_repository, "obtener_para_actualizar", AsyncMock(return_value=None)
    )
    insertar = AsyncMock()
    monkeypatch.setattr(pagos_reservacion_repository, "crear", insertar)

    body = PagosReservacionCreate(
        reservacion_id=RESERVACION_ID, metodo_pago_id=uuid4(), monto=Decimal("100.00")
    )
    with pytest.raises(HTTPException) as exc:
        await pagos_reservacion.crear(_conn(), body, uuid4(), str(uuid4()))

    assert exc.value.status_code == 404
    insertar.assert_not_awaited()
