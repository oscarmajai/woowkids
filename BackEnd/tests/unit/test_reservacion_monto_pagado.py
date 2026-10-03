"""Cada alta, edición o baja de un pago de reservación recalcula
`reservaciones.monto_pagado` en la misma transacción, con la reservación
bloqueada (C3). Sin BD: repositories simulados; el SQL real se prueba en
tests/integration/test_reservaciones_saldo_pg.py."""

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.repositories import (
    metodos_pago_repository,
    pagos_reservacion_repository,
    reservaciones_repository,
)
from app.schemas.pagos_reservacion import (
    PagoReservacionItem,
    PagosReservacionCompletarRequest,
    PagosReservacionCreate,
    PagosReservacionUpdate,
)
from app.services import pagos_reservacion, reservaciones_vencidas_scheduler

RESERVACION_ID = uuid4()
PAGO_ID = uuid4()


def _conn() -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def transaccion() -> Any:
        yield

    conn.transaction = transaccion
    return conn


def _pago(monto: str = "2000.00") -> dict[str, Any]:
    return {
        "id": PAGO_ID,
        "reservacion_id": RESERVACION_ID,
        "metodo_pago_id": uuid4(),
        "monto": Decimal(monto),
        "fecha_pago": datetime.now(UTC),
        "notas": None,
        "tipo": "pago",
        "creado_por": None,
    }


@pytest.fixture
def mocks(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    reservacion = {
        "id": RESERVACION_ID,
        "precio_total": Decimal("13815.00"),
        "telefono_cliente": "",
        "sucursal_id": uuid4(),
    }
    bloquear = AsyncMock(return_value=reservacion)
    recalcular = AsyncMock()
    monkeypatch.setattr(reservaciones_repository, "obtener_para_actualizar", bloquear)
    monkeypatch.setattr(reservaciones_repository, "recalcular_monto_pagado", recalcular)
    monkeypatch.setattr(reservaciones_repository, "obtener", AsyncMock(return_value=reservacion))
    monkeypatch.setattr(metodos_pago_repository, "existe", AsyncMock(return_value=True))
    monkeypatch.setattr(
        metodos_pago_repository, "obtener_ids_por_tipo", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(
        pagos_reservacion_repository, "sumar_pagos", AsyncMock(return_value=Decimal("5526"))
    )
    monkeypatch.setattr(pagos_reservacion_repository, "crear", AsyncMock(return_value=_pago()))
    monkeypatch.setattr(pagos_reservacion_repository, "obtener", AsyncMock(return_value=_pago()))
    monkeypatch.setattr(
        pagos_reservacion_repository, "actualizar", AsyncMock(return_value=_pago("1500.00"))
    )
    monkeypatch.setattr(pagos_reservacion_repository, "eliminar", AsyncMock(return_value=True))
    monkeypatch.setattr(pagos_reservacion, "registrar_movimiento_caja", AsyncMock())
    monkeypatch.setattr(pagos_reservacion, "registrar_cambio_caja", AsyncMock())
    return {"bloquear": bloquear, "recalcular": recalcular}


async def test_un_abono_actualiza_el_saldo_de_la_reservacion(mocks: dict) -> None:
    body = PagosReservacionCreate(
        reservacion_id=RESERVACION_ID, metodo_pago_id=uuid4(), monto=Decimal("2000")
    )
    await pagos_reservacion.crear(_conn(), body, uuid4(), str(uuid4()))

    mocks["bloquear"].assert_awaited_once()
    mocks["recalcular"].assert_awaited_once()
    assert mocks["recalcular"].await_args.args[1] == RESERVACION_ID


async def test_el_cambio_se_descuenta_despues_de_registrarlo(
    mocks: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    efectivo = uuid4()
    monkeypatch.setattr(
        metodos_pago_repository, "obtener_ids_por_tipo", AsyncMock(return_value={efectivo})
    )
    body = PagosReservacionCompletarRequest(
        reservacion_id=RESERVACION_ID,
        pagos=[PagoReservacionItem(metodo_pago_id=efectivo, monto=Decimal("6000"))],
        cambio=Decimal("80"),
    )
    await pagos_reservacion.completar(_conn(), body, uuid4(), str(uuid4()))

    # Una vez por el pago y otra tras registrar el cambio.
    assert mocks["recalcular"].await_count == 2


async def test_editar_o_borrar_un_pago_recalcula_el_saldo(mocks: dict) -> None:
    await pagos_reservacion.actualizar(
        _conn(), PAGO_ID, PagosReservacionUpdate(monto=Decimal("1500"))
    )
    await pagos_reservacion.eliminar(_conn(), PAGO_ID)

    assert mocks["recalcular"].await_count == 2
    assert mocks["bloquear"].await_count == 2


async def test_scheduler_reporta_el_saldo_real(monkeypatch: pytest.MonkeyPatch) -> None:
    vencida = {
        "id": uuid4(),
        "nombre_cliente": "Ricardo",
        "fecha_evento": date(2026, 10, 8),
        "precio_total": Decimal("13815.00"),
        "anticipo": Decimal("5526.00"),
        "saldo_pendiente": Decimal("6289.00"),
    }
    monkeypatch.setattr(
        reservaciones_repository, "listar_vencidas_sin_liquidar", AsyncMock(return_value=[vencida])
    )
    cancelar = AsyncMock()
    monkeypatch.setattr(reservaciones_repository, "cancelar_por_falta_de_pago", cancelar)
    avisos: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        reservaciones_vencidas_scheduler.logger, "warning", lambda *a: avisos.append(a)
    )

    assert await reservaciones_vencidas_scheduler.revisar_reservaciones_vencidas(MagicMock()) == 1
    assert avisos[0][-1] == Decimal("6289.00")
