"""Manejador global de errores de PostgreSQL (sin BD).

Una app FastAPI mínima con los manejadores de ``app.exceptions.manejadores``
y rutas que lanzan cada error de asyncpg: debe responder 409/422 con el
formato ``{"detail": {"code", "message"}}`` y un mensaje genérico en español,
sin filtrar el detalle técnico al cliente, y registrarlo en el log."""

from __future__ import annotations

import logging
from typing import Any

import asyncpg
import httpx
import pytest
from app.exceptions.manejadores import registrar_manejadores, respuesta_para
from asyncpg.exceptions._base import DataError as ErrorDeArgumentoAsyncpg
from fastapi import FastAPI, HTTPException

_SECRETO = "constraint_secreto_xyz"


def _error_pg(sqlstate: str, mensaje: str = "error de prueba") -> Exception:
    return asyncpg.PostgresError.new(
        {
            "C": sqlstate,
            "M": mensaje,
            "D": f"Key (id)=(1) detalle {_SECRETO}.",
            "n": _SECRETO,
            "t": "tabla_secreta",
        }
    )


_CASOS: list[tuple[str, str, int, str]] = [
    # (sqlstate, mensaje de PostgreSQL, status, code)
    ("23505", "duplicate key value violates unique constraint", 409, "REGISTRO_DUPLICADO"),
    ("23P01", "conflicting key value violates exclusion constraint", 409, "REGISTRO_EN_CONFLICTO"),
    (
        "23503",
        'insert or update on table "x" violates foreign key constraint "fk"',
        422,
        "REFERENCIA_INVALIDA",
    ),
    (
        "23503",
        'update or delete on table "x" violates foreign key constraint "fk" on table "y"',
        409,
        "REGISTRO_EN_USO",
    ),
    ("23514", "new row violates check constraint", 422, "VALOR_NO_PERMITIDO"),
    ("23502", "null value in column violates not-null constraint", 422, "DATO_REQUERIDO"),
    ("23000", "integrity constraint violation", 409, "CONFLICT"),
    ("22003", "numeric field overflow", 422, "VALOR_FUERA_DE_RANGO"),
    ("22001", "value too long for type character varying(10)", 422, "TEXTO_DEMASIADO_LARGO"),
    ("22P02", 'invalid input syntax for type integer: "xx"', 422, "FORMATO_INVALIDO"),
    ("22007", 'invalid input syntax for type date: "xx"', 422, "DATOS_INVALIDOS"),
    ("22000", "data exception", 422, "DATOS_INVALIDOS"),
]


def _app() -> FastAPI:
    app = FastAPI()
    registrar_manejadores(app)

    @app.api_route("/pg/{sqlstate}", methods=["GET", "POST", "DELETE"])
    async def lanzar(sqlstate: str, mensaje: str = "error de prueba") -> None:
        raise _error_pg(sqlstate, mensaje)

    @app.get("/argumento")
    async def argumento() -> None:
        raise ErrorDeArgumentoAsyncpg(
            f"invalid input for query argument $1: 3000000000 (value out of int32 range) "
            f"{_SECRETO}"
        )

    @app.get("/http")
    async def http() -> None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "x"})

    @app.get("/otro")
    async def otro() -> None:
        raise asyncpg.PostgresError.new({"C": "42P01", "M": "relation does not exist"})

    return app


async def _cliente() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _assert_formato(resp: httpx.Response, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    cuerpo = resp.json()
    assert cuerpo == {"detail": {"code": code, "message": cuerpo["detail"]["message"]}}
    assert cuerpo["detail"]["message"]
    for secreto in (_SECRETO, "tabla_secreta", "constraint", "violates", "Key ("):
        assert secreto not in resp.text
    return cuerpo["detail"]


@pytest.mark.parametrize(("sqlstate", "mensaje", "status", "code"), _CASOS)
async def test_error_de_bd_responde_codigo_y_formato(
    sqlstate: str, mensaje: str, status: int, code: str, caplog: Any
) -> None:
    async with await _cliente() as c:
        with caplog.at_level(logging.WARNING, logger="mercury.errores_bd"):
            resp = await c.post(f"/pg/{sqlstate}", params={"mensaje": mensaje})

    _assert_formato(resp, status, code)
    # El detalle técnico queda en el log, con la ruta.
    assert _SECRETO in caplog.text
    assert "tabla_secreta" in caplog.text
    assert f"/pg/{sqlstate}" in caplog.text


async def test_mensajes_en_espanol() -> None:
    async with await _cliente() as c:
        unique = await c.post("/pg/23505")
        fk = await c.post("/pg/23503", params={"mensaje": "insert or update on table"})
        rango = await c.post("/pg/22003")
    assert unique.json()["detail"]["message"] == "Ya existe un registro con esos datos."
    assert fk.json()["detail"]["message"] == (
        "Uno de los datos hace referencia a un registro que no existe."
    )
    assert rango.json()["detail"]["message"] == (
        "Uno de los valores numéricos está fuera del rango permitido."
    )


async def test_llave_foranea_en_un_delete_es_registro_en_uso() -> None:
    """Aunque el mensaje de PostgreSQL venga traducido, un DELETE que choca
    con una llave foránea significa que el registro está en uso."""
    async with await _cliente() as c:
        resp = await c.delete("/pg/23503", params={"mensaje": "mensaje localizado"})
    _assert_formato(resp, 409, "REGISTRO_EN_USO")


async def test_error_de_argumento_de_asyncpg_responde_422() -> None:
    async with await _cliente() as c:
        resp = await c.get("/argumento")
    _assert_formato(resp, 422, "DATOS_INVALIDOS")
    assert "int32" not in resp.text


async def test_no_toca_las_http_exception() -> None:
    async with await _cliente() as c:
        resp = await c.get("/http")
    assert resp.status_code == 404
    assert resp.json() == {"detail": {"code": "NOT_FOUND", "message": "x"}}


async def test_otros_errores_de_postgres_siguen_siendo_500() -> None:
    """Un error de programación (tabla inexistente) no es culpa del cliente."""
    async with await _cliente() as c:
        resp = await c.get("/otro")
    assert resp.status_code == 500


def test_respuesta_para_no_reconoce_errores_ajenos() -> None:
    assert respuesta_para(ValueError("x")).code == "DATOS_INVALIDOS"


def test_la_app_real_registra_los_manejadores() -> None:
    from app.main import app

    for clase in (
        asyncpg.IntegrityConstraintViolationError,
        asyncpg.DataError,
        ErrorDeArgumentoAsyncpg,
    ):
        assert clase in app.exception_handlers
