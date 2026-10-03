"""M8: qué horario está vigente a la hora local de la sucursal (GET
/turnos-caja/turnos marca `vigente`). Sin BD."""

from datetime import datetime, time
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.services import turnos_caja_service as svc

SVC = "app.services.turnos_caja_service"


# ── M8: horario vigente ──────────────────────────────────────────────────────

# 2026-10-03 es sábado (weekday 5).
SABADO_0124 = datetime(2026, 10, 3, 1, 24)
SABADO_1600 = datetime(2026, 10, 3, 16, 0)


@pytest.mark.parametrize(
    ("inicio", "fin", "dias", "ahora", "esperado"),
    [
        # El caso del bug: a la 01:24 el Vespertino (15:00-23:59) no está vigente.
        (time(15, 0), time(23, 59), None, SABADO_0124, False),
        (time(15, 0), time(23, 59), None, SABADO_1600, True),
        (time(8, 0), time(15, 0), None, SABADO_1600, False),
        # Extremos incluidos, a nivel de minuto.
        (time(15, 0), time(23, 59), None, datetime(2026, 10, 3, 23, 59, 40), True),
        (time(15, 0), time(23, 59), None, datetime(2026, 10, 3, 15, 0), True),
        # Días: 0 = lunes ... 6 = domingo.
        (time(8, 0), time(20, 0), [5, 6], SABADO_1600, True),
        (time(8, 0), time(20, 0), [0, 1, 2, 3, 4], SABADO_1600, False),
        (time(8, 0), time(20, 0), [], SABADO_1600, True),
        # Cruza la medianoche: la madrugada cuenta como del día en que empezó.
        (time(22, 0), time(6, 0), None, SABADO_0124, True),
        (time(22, 0), time(6, 0), [4], SABADO_0124, True),  # empezó el viernes
        (time(22, 0), time(6, 0), [5], SABADO_0124, False),
        (time(22, 0), time(6, 0), None, SABADO_1600, False),
    ],
)
def test_horario_vigente(
    inicio: time, fin: time, dias: list[int] | None, ahora: datetime, esperado: bool
) -> None:
    assert svc.horario_vigente(inicio, fin, dias, ahora) is esperado


async def test_obtener_turnos_marca_el_vigente() -> None:
    filas = [
        {"id": uuid4(), "nombre": "Matutino", "hora_inicio": time(8), "hora_fin": time(15)},
        {
            "id": uuid4(),
            "nombre": "Vespertino",
            "hora_inicio": time(15),
            "hora_fin": time(23, 59),
            "dias": [5, 6],
        },
    ]
    with patch(f"{SVC}.listar_turnos", AsyncMock(return_value=filas)):
        turnos = await svc.obtener_turnos(object(), SABADO_1600)  # type: ignore[arg-type]
        sin_hora = await svc.obtener_turnos(object())  # type: ignore[arg-type]

    assert [(t.nombre, t.vigente) for t in turnos] == [("Matutino", False), ("Vespertino", True)]
    assert turnos[1].dias == [5, 6]
    assert not any(t.vigente for t in sin_hora)
