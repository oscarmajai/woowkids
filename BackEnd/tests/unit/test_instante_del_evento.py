from datetime import UTC, date, time

import pytest
import pytz
from app.services.estancias import instante_del_evento


def test_un_evento_de_las_9_en_mexico_es_a_las_15_utc() -> None:
    entrada = instante_del_evento(date(2026, 10, 8), time(9, 0), "America/Mexico_City")
    assert entrada.astimezone(UTC).hour == 15
    assert entrada.utcoffset() is not None


def test_la_zona_de_la_sucursal_manda() -> None:
    cancun = instante_del_evento(date(2026, 10, 8), time(9, 0), "America/Cancun")
    tijuana = instante_del_evento(date(2026, 10, 8), time(9, 0), "America/Tijuana")
    assert cancun.astimezone(UTC).hour == 14
    assert tijuana.astimezone(UTC).hour == 16


def test_la_duracion_no_cambia_con_la_zona() -> None:
    inicio = instante_del_evento(date(2026, 10, 8), time(9, 0), "America/Mexico_City")
    fin = instante_del_evento(date(2026, 10, 8), time(10, 0), "America/Mexico_City")
    assert (fin - inicio).total_seconds() == 3600


def test_una_zona_invalida_falla() -> None:
    with pytest.raises(pytz.UnknownTimeZoneError):
        instante_del_evento(date(2026, 10, 8), time(9, 0), "No/Existe")
