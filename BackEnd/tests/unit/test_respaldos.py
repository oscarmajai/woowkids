"""Bloqueante de entrega: el sistema no se respaldaba solo.

Piezas puras de scripts/respaldos.py (la prueba de punta a punta, con pg_dump,
MinIO y restauración, se hizo contra el contenedor todo en uno) y el aviso al
AdministradorSistema cuando los respaldos fallan o dejan de hacerse.
"""

import importlib.util
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from app.services import respaldos_service

_RUTA = Path(__file__).resolve().parents[2] / "scripts" / "respaldos.py"
_spec = importlib.util.spec_from_file_location("respaldos", _RUTA)
assert _spec and _spec.loader
respaldos = importlib.util.module_from_spec(_spec)
sys.modules["respaldos"] = respaldos
_spec.loader.exec_module(respaldos)


def _cfg(tmp_path: Path, **kw):
    base = {
        "database_url": "postgresql://u:p@h/db",
        "dir": tmp_path,
        "cada_horas": 6,
        "dias_conservar": 14,
        "minimo_conservar": 3,
        "zona": "America/Mexico_City",
    }
    base.update(kw)
    return respaldos.Config(**base)


@pytest.mark.parametrize(
    "llave", ["../fuera.jpg", "/abs.jpg", "a/../../b.jpg", ".indice.json", "x.parcial"]
)
def test_ruta_segura_rechaza_llaves_que_salen_del_respaldo(tmp_path, llave):
    with pytest.raises(ValueError):
        respaldos.ruta_segura(tmp_path, llave)


def test_ruta_segura_respeta_las_carpetas_de_la_llave(tmp_path):
    ruta = respaldos.ruta_segura(tmp_path, "uploads/identificaciones/ine.jpg")
    assert ruta == tmp_path / "uploads" / "identificaciones" / "ine.jpg"


def _dump(cfg, nombre: str, dias: float) -> Path:
    cfg.dir_bd.mkdir(parents=True, exist_ok=True)
    ruta = cfg.dir_bd / f"woowkids-{nombre}.dump"
    ruta.write_bytes(b"x")
    hace = time.time() - dias * 86400
    os.utime(ruta, (hace, hace))
    return ruta


def test_depurar_borra_lo_viejo_y_deja_siempre_los_mas_recientes(tmp_path):
    cfg = _cfg(tmp_path, dias_conservar=14, minimo_conservar=3)
    recientes = [_dump(cfg, f"r{i}", i) for i in range(5)]
    viejos = [_dump(cfg, f"v{i}", 20 + i) for i in range(3)]

    borrados = respaldos.depurar(cfg)

    assert set(borrados) == set(viejos)
    assert all(r.exists() for r in recientes)


def test_depurar_no_deja_sin_respaldos_aunque_todos_sean_viejos(tmp_path):
    cfg = _cfg(tmp_path, dias_conservar=1, minimo_conservar=3)
    todos = [_dump(cfg, f"v{i}", 30 + i) for i in range(5)]

    respaldos.depurar(cfg)

    assert [p for p in todos if p.exists()] == todos[:3]


def test_en_todo_en_uno_arma_la_url_con_las_variables_de_postgres(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_USER", "admin")
    monkeypatch.setenv("POSTGRES_PASSWORD", "cl@ve/rara")
    monkeypatch.setenv("POSTGRES_DB", "woowkids")
    assert respaldos.Config.desde_entorno().database_url == (
        "postgresql://admin:cl%40ve%2Frara@127.0.0.1:5432/woowkids"
    )


def test_url_de_mantenimiento_apunta_a_postgres():
    url, bd = respaldos._url_mantenimiento("postgresql://u:p@db:5432/woowkids")
    assert (url, bd) == ("postgresql://u:p@db:5432/postgres", "woowkids")


def _fila(exitoso: bool, hace_horas: float, error: str | None = None) -> dict:
    inicio = datetime.now(UTC) - timedelta(hours=hace_horas)
    return {
        "inicio": inicio,
        "fin": inicio,
        "exitoso": exitoso,
        "motivo": "programado",
        "nombre": "woowkids-x",
        "tamano_bd": 1,
        "archivos": 0,
        "error": error,
    }


async def _estado(ultimo_exitoso, ultimo_intento):
    async def ultimo(_conn, *, exitoso=None):
        return ultimo_exitoso if exitoso else ultimo_intento

    with patch.object(respaldos_service.respaldos_repository, "ultimo", ultimo):
        return await respaldos_service.estado(MagicMock())


@pytest.mark.asyncio
async def test_sin_ningun_respaldo_avisa():
    estado = await _estado(None, None)
    assert estado.alerta and "Todavía no hay" in (estado.mensaje or "")


@pytest.mark.asyncio
async def test_si_el_ultimo_intento_fallo_avisa():
    estado = await _estado(_fila(True, 7), _fila(False, 1, "disco lleno"))
    assert estado.alerta and "falló" in (estado.mensaje or "")


@pytest.mark.asyncio
async def test_si_hace_dias_que_no_hay_respaldo_avisa():
    fila = _fila(True, respaldos_service.HORAS_ALERTA + 1)
    estado = await _estado(fila, fila)
    assert estado.alerta


@pytest.mark.asyncio
async def test_con_respaldo_reciente_no_avisa():
    fila = _fila(True, 2)
    estado = await _estado(fila, fila)
    assert not estado.alerta and estado.mensaje is None


def test_solo_los_programados_cuentan_para_el_horario(tmp_path):
    cfg = _cfg(tmp_path)
    assert respaldos._es_programado(_dump(cfg, "20261003-201011", 0))
    assert not respaldos._es_programado(_dump(cfg, "20261003-201011-antes-de-migrar", 0))
    assert not respaldos._es_programado(_dump(cfg, "20261003-201011-manual", 0))
