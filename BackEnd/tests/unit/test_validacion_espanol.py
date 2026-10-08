"""Los errores de validación de la petición salen en español, con el
campo afectado, y conservan la forma estructurada de FastAPI (type, loc,
input, ctx) para los clientes que la leen. Sin BD."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import UUID

import httpx
import pytest
from app.exceptions.manejadores import registrar_manejadores
from app.exceptions.validacion import mensaje_en_espanol
from app.schemas.movimiento_inventario import MovimientoManualCreate
from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator


class _Cuerpo(BaseModel):
    stock_inicial: int = Field(ge=0)
    nombre: str = Field(min_length=1, max_length=5)
    tipo: Literal["E", "S", "M"]
    n: int = 0

    @field_validator("n")
    @classmethod
    def _sin_tres(cls, v: int) -> int:
        if v == 3:
            raise ValueError("el tres no se permite")
        return v


def _app() -> FastAPI:
    app = FastAPI()
    registrar_manejadores(app)

    @app.post("/insumos/{insumo_id}/movimientos")
    async def movimiento(insumo_id: UUID, body: MovimientoManualCreate) -> dict[str, str]:
        return {}

    @app.post("/cuerpo")
    async def cuerpo(body: _Cuerpo, pagina: int = 1) -> dict[str, str]:
        return {}

    return app


async def _post(path: str, **kwargs: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post(path, **kwargs)


def _por_campo(resp: httpx.Response) -> dict[str, dict[str, Any]]:
    assert resp.status_code == 422, resp.text
    return {str(e["loc"][-1]): e for e in resp.json()["detail"]}


async def test_cantidad_negativa_del_ajuste_manual_sale_en_espanol() -> None:
    """Ajuste manual de inventario con cantidad -5."""
    resp = await _post(f"/insumos/{UUID(int=1)}/movimientos", json={"tipo": "E", "cantidad": "-5"})
    errores = _por_campo(resp)
    e = errores["cantidad"]
    assert e["msg"] == "cantidad: debe ser mayor que 0"
    # Se conserva el detalle estructurado.
    assert e["type"] == "greater_than"
    assert e["loc"] == ["body", "cantidad"]
    assert set(e["ctx"]) == {"gt"}
    assert "Input should" not in resp.text


async def test_varios_tipos_de_error() -> None:
    resp = await _post(
        "/cuerpo",
        params={"pagina": "zz"},
        json={"stock_inicial": -5, "nombre": "", "tipo": "Q", "n": 3},
    )
    errores = _por_campo(resp)
    assert errores["stock_inicial"]["msg"] == "stock inicial: debe ser mayor o igual que 0"
    assert errores["nombre"]["msg"] == "nombre: no puede estar vacío"
    assert errores["tipo"]["msg"] == "tipo: debe ser uno de: 'E', 'S' o 'M'"
    assert errores["n"]["msg"] == "n: el tres no se permite"
    assert errores["pagina"]["msg"] == "pagina: debe ser un número entero"
    for e in errores.values():
        assert not e["msg"].startswith(("Input should", "Value error", "String should"))


async def test_campo_faltante_y_path_invalido() -> None:
    resp = await _post("/insumos/abc/movimientos", json={"tipo": "E"})
    errores = _por_campo(resp)
    assert errores["insumo_id"]["msg"] == "insumo id: debe ser un identificador (UUID) válido"
    assert errores["cantidad"]["msg"] == "cantidad: es obligatorio"


async def test_json_invalido() -> None:
    resp = await _post(
        "/cuerpo", content="no es json", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["msg"] == "no es un JSON válido"


@pytest.mark.parametrize(
    ("error", "esperado"),
    [
        (
            {"type": "less_than_equal", "loc": ("body", "x"), "ctx": {"le": 10}},
            "x: debe ser menor o igual que 10",
        ),
        (
            {"type": "string_too_long", "loc": ("body", "nombre"), "ctx": {"max_length": 150}},
            "nombre: admite como máximo 150 caracteres",
        ),
        (
            {
                "type": "decimal_max_places",
                "loc": ("body", "detalles", 0, "costo"),
                "ctx": {"decimal_places": 2},
            },
            "costo: admite como máximo 2 decimales",
        ),
        (
            {
                "type": "value_error",
                "loc": ("body",),
                "msg": "Value error, max_invitados debe ser mayor",
            },
            "max_invitados debe ser mayor",
        ),
        # Tipo de Pydantic sin traducción propia → genérico.
        ({"type": "is_instance_of", "loc": ("query", "q")}, "q: no es un valor válido"),
        # PydanticCustomError nuestro: su mensaje ya está en español.
        (
            {
                "type": "password_corta",
                "loc": ("body", "password"),
                "msg": "La contraseña debe tener al menos 8 caracteres.",
            },
            "password: La contraseña debe tener al menos 8 caracteres.",
        ),
        ({"type": "greater_than", "loc": ("body", "x"), "ctx": {}}, "x: no es un valor válido"),
    ],
)
def test_mensaje_en_espanol(error: dict[str, Any], esperado: str) -> None:
    assert mensaje_en_espanol(error) == esperado


@pytest.fixture
async def app_real() -> AsyncIterator[httpx.AsyncClient]:
    from app.core.database import get_db
    from app.main import app

    async def _sin_bd() -> AsyncIterator[None]:
        yield None

    app.dependency_overrides[get_db] = _sin_bd
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


async def test_la_app_real_traduce_la_validacion(app_real: httpx.AsyncClient) -> None:
    resp = await app_real.post("/api/auth/login", json={"email": "no-es-correo"})
    errores = _por_campo(resp)
    assert errores["email"]["msg"] == "email: debe ser un correo electrónico válido"
    assert errores["password"]["msg"] == "password: es obligatorio"
