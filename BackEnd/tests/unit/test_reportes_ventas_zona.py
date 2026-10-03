"""M4: los periodos del historial de ventas se calculan con la hora local de la
sucursal, no con la del servidor (UTC)."""

from datetime import datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.exceptions import DatosInvalidos, NoEncontrado
from app.services import pago_service

# 3 oct 2026, 19:00 en México: en UTC ya es el 4 de octubre.
AHORA_LOCAL = datetime(2026, 10, 3, 19, 0)


def test_calcular_desde_parte_de_la_hora_local_de_la_sucursal() -> None:
    assert pago_service._calcular_desde("hoy", AHORA_LOCAL) == datetime(2026, 10, 3)
    # El 3 de octubre de 2026 es sábado: la semana empieza el lunes 28.
    assert pago_service._calcular_desde("semana", AHORA_LOCAL) == datetime(2026, 9, 28)
    assert pago_service._calcular_desde("mes", AHORA_LOCAL) == datetime(2026, 10, 1)


@pytest.mark.asyncio
async def test_periodo_usa_la_hora_de_la_sucursal_y_fin_de_dia_exclusivo(monkeypatch) -> None:
    monkeypatch.setattr(
        pago_service.sucursales, "ahora_en_sucursal", AsyncMock(return_value=AHORA_LOCAL)
    )
    desde, hasta = await pago_service._periodo(AsyncMock(), uuid4(), "hoy", None, None)
    assert (desde, hasta) == (datetime(2026, 10, 3), None)

    desde, hasta = await pago_service._periodo(
        AsyncMock(), uuid4(), "hoy", "2026-10-01", "2026-10-03"
    )
    assert desde == datetime(2026, 10, 1)
    assert hasta == datetime(2026, 10, 4)


@pytest.mark.asyncio
async def test_periodo_rechaza_fechas_invalidas_con_400(monkeypatch) -> None:
    monkeypatch.setattr(
        pago_service.sucursales, "ahora_en_sucursal", AsyncMock(return_value=AHORA_LOCAL)
    )
    with pytest.raises(DatosInvalidos):
        await pago_service._periodo(AsyncMock(), uuid4(), "hoy", "03/10/2026", None)


@pytest.mark.asyncio
async def test_periodo_sin_sucursal_es_404(monkeypatch) -> None:
    monkeypatch.setattr(pago_service.sucursales, "ahora_en_sucursal", AsyncMock(return_value=None))
    with pytest.raises(NoEncontrado):
        await pago_service._periodo(AsyncMock(), uuid4(), "hoy", None, None)
