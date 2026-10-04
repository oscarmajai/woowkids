"""N-1 (prueba E2E de v1.2.0): el registro de entrada reutilizaba al tutor
solo por teléfono y descartaba el nombre capturado; la salida verificaba
contra la persona equivocada. Ahora se reutiliza solo si coinciden teléfono
y nombre (sin distinguir mayúsculas, acentos ni espacios)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app.services import estancias as m

SUCURSAL = uuid4()
USUARIO = uuid4()


def _tutor(nombre: str) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "nombreCompleto": nombre,
        "telefono": "3312345678",
        "sucursal_id": SUCURSAL,
    }


def test_normalizar_nombre_ignora_mayusculas_acentos_y_espacios() -> None:
    assert m.normalizar_nombre("  Ana  GÓMEZ Torres ") == m.normalizar_nombre("ana gomez torres")
    assert m.normalizar_nombre("Lucía Pérez") != m.normalizar_nombre("Ana Gómez")


async def test_mismo_telefono_otro_nombre_crea_un_tutor_nuevo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anterior = _tutor("Ana Gómez Torres")
    nuevo_id = uuid4()
    crear = AsyncMock(return_value=nuevo_id)
    monkeypatch.setattr(m, "get_tutores_by_phone", AsyncMock(return_value=[anterior]))
    monkeypatch.setattr(m, "tutor_create", crear)

    tutor_id = await m._resolver_tutor(
        object(),  # type: ignore[arg-type]
        SUCURSAL,
        "3312345678",
        "Lucía Pérez Ramos",
        USUARIO,
    )

    assert tutor_id == nuevo_id
    crear.assert_awaited_once()
    assert crear.await_args is not None
    assert crear.await_args.args[2] == "Lucía Pérez Ramos"


async def test_mismo_telefono_y_nombre_reutiliza_al_tutor(monkeypatch: pytest.MonkeyPatch) -> None:
    otro = _tutor("Ana Gómez Torres")
    mismo = _tutor("Lucía Pérez Ramos")
    crear = AsyncMock()
    monkeypatch.setattr(m, "get_tutores_by_phone", AsyncMock(return_value=[otro, mismo]))
    monkeypatch.setattr(m, "tutor_create", crear)

    tutor_id = await m._resolver_tutor(
        object(),  # type: ignore[arg-type]
        SUCURSAL,
        "3312345678",
        "  lucia  perez RAMOS ",
        USUARIO,
    )

    assert tutor_id == mismo["id"]
    crear.assert_not_awaited()
