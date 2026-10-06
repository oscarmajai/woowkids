"""Horarios por sucursal.

- Globales (sucursal_id NULL): solo el AdministradorSistema los edita.
- Los nuevos se crean en la sucursal de quien los crea; el Administrador de
  sucursal crea y edita solo los suyos (los de otra sucursal: 404).
- Listados: los de la sucursal más los globales.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from app.schemas.auth import TokenData
from app.schemas.horarios_cajas import HorarioCreate, HorarioUpdate
from app.services import horarios_service
from fastapi import HTTPException
from pydantic import ValidationError

REPO = "app.services.horarios_service.horarios_repository"
SUC_A = UUID("aaaaaaaa-0000-0000-0000-00000000000a")
SUC_B = UUID("bbbbbbbb-0000-0000-0000-00000000000b")
HID = str(uuid4())
CONN: Any = object()


def _usuario(rol: str = "Administrador", branch_id: UUID | None = SUC_B) -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="admin@woowkids.test",
        role=rol,
        branch_id=branch_id,
        permissions=[],
        jti=str(uuid4()),
        exp=datetime.now(tz=UTC) + timedelta(hours=1),
    )


def _horario(sucursal_id: UUID | None) -> dict[str, Any]:
    return {
        "id": HID,
        "nombre": "Matutino",
        "hora_inicio": "08:00",
        "hora_fin": "14:00",
        "activo": True,
        "dias": None,
        "sucursal_id": str(sucursal_id) if sucursal_id else None,
    }


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    mocks = {
        "listar_horarios": AsyncMock(return_value=[]),
        "existe_nombre": AsyncMock(return_value=False),
        "get_horario_por_id": AsyncMock(return_value=_horario(SUC_B)),
        "crear_horario": AsyncMock(side_effect=lambda conn, **kw: _horario(kw["sucursal_id"])),
        "actualizar_horario": AsyncMock(return_value=_horario(SUC_B)),
        "eliminar_horario": AsyncMock(return_value=True),
    }
    for nombre, mock in mocks.items():
        monkeypatch.setattr(f"{REPO}.{nombre}", mock)
    return mocks


_CREAR = HorarioCreate(nombre="Matutino", hora_inicio="08:00", hora_fin="14:00")


async def test_admin_crea_el_horario_en_su_sucursal(repo: dict[str, AsyncMock]) -> None:
    creado = await horarios_service.crear(CONN, _usuario(), _CREAR)
    assert repo["crear_horario"].await_args.kwargs["sucursal_id"] == SUC_B
    assert creado.sucursal_id == str(SUC_B)


async def test_admin_no_crea_horarios_en_otra_sucursal(repo: dict[str, AsyncMock]) -> None:
    payload = _CREAR.model_copy(update={"sucursal_id": SUC_A})
    with pytest.raises(HTTPException) as exc:
        await horarios_service.crear(CONN, _usuario(), payload)
    assert exc.value.status_code == 403
    repo["crear_horario"].assert_not_called()


async def test_sistema_sin_selector_crea_un_horario_global(repo: dict[str, AsyncMock]) -> None:
    creado = await horarios_service.crear(CONN, _usuario("AdministradorSistema", None), _CREAR)
    assert repo["crear_horario"].await_args.kwargs["sucursal_id"] is None
    assert creado.sucursal_id is None


async def test_nombre_repetido_con_un_global_o_de_la_sucursal_da_409(
    repo: dict[str, AsyncMock],
) -> None:
    repo["existe_nombre"].return_value = True
    with pytest.raises(HTTPException) as exc:
        await horarios_service.crear(CONN, _usuario(), _CREAR)
    assert exc.value.status_code == 409
    assert repo["existe_nombre"].await_args.args[1:] == ("Matutino", SUC_B)
    repo["crear_horario"].assert_not_called()


async def test_listado_del_admin_pide_su_sucursal_y_los_globales(
    repo: dict[str, AsyncMock],
) -> None:
    await horarios_service.listar(CONN, _usuario(), None)
    assert repo["listar_horarios"].await_args.args[1] == SUC_B
    with pytest.raises(HTTPException) as exc:
        await horarios_service.listar(CONN, _usuario(), SUC_A)
    assert exc.value.status_code == 403


async def test_sistema_sin_selector_lista_todos(repo: dict[str, AsyncMock]) -> None:
    await horarios_service.listar(CONN, _usuario("AdministradorSistema", None), None)
    assert repo["listar_horarios"].await_args.args[1] is None


async def test_admin_no_edita_ni_desactiva_un_horario_global(repo: dict[str, AsyncMock]) -> None:
    repo["get_horario_por_id"].return_value = _horario(None)
    with pytest.raises(HTTPException) as exc:
        await horarios_service.editar(CONN, _usuario(), HID, HorarioUpdate(nombre="Otro"))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "HORARIO_GLOBAL"
    with pytest.raises(HTTPException) as exc:
        await horarios_service.eliminar(CONN, _usuario(), HID)
    assert exc.value.status_code == 403
    repo["actualizar_horario"].assert_not_called()
    repo["eliminar_horario"].assert_not_called()


async def test_admin_no_ve_el_horario_de_otra_sucursal(repo: dict[str, AsyncMock]) -> None:
    repo["get_horario_por_id"].return_value = _horario(SUC_A)
    with pytest.raises(HTTPException) as exc:
        await horarios_service.editar(CONN, _usuario(), HID, HorarioUpdate(activo=False))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await horarios_service.eliminar(CONN, _usuario(), HID)
    assert exc.value.status_code == 404
    repo["actualizar_horario"].assert_not_called()
    repo["eliminar_horario"].assert_not_called()


async def test_admin_edita_y_desactiva_los_de_su_sucursal(repo: dict[str, AsyncMock]) -> None:
    await horarios_service.editar(CONN, _usuario(), HID, HorarioUpdate(hora_fin="15:00"))
    await horarios_service.eliminar(CONN, _usuario(), HID)
    repo["actualizar_horario"].assert_awaited_once()
    repo["eliminar_horario"].assert_awaited_once()


async def test_sistema_edita_los_globales(repo: dict[str, AsyncMock]) -> None:
    repo["get_horario_por_id"].return_value = _horario(None)
    sistema = _usuario("AdministradorSistema", None)
    await horarios_service.editar(CONN, sistema, HID, HorarioUpdate(nombre="Matutino general"))
    repo["actualizar_horario"].assert_awaited_once()
    assert repo["existe_nombre"].await_args.args[2] is None


async def test_id_que_no_es_uuid_da_404(repo: dict[str, AsyncMock]) -> None:
    with pytest.raises(HTTPException) as exc:
        await horarios_service.eliminar(CONN, _usuario(), "no-es-uuid")
    assert exc.value.status_code == 404


# ── Hora inválida → 422, no 500 ─────────────────────────────────────────────


@pytest.mark.parametrize("hora", ["xx", "25:00", "8 am", ""])
def test_hora_invalida_es_error_de_validacion(hora: str) -> None:
    with pytest.raises(ValidationError, match="Hora inválida"):
        HorarioUpdate(hora_inicio=hora)
    with pytest.raises(ValidationError, match="Hora inválida"):
        HorarioCreate(nombre="X", hora_inicio="08:00", hora_fin=hora)


def test_hora_valida_se_acepta() -> None:
    assert HorarioUpdate(hora_fin="23:59").hora_fin == "23:59"
