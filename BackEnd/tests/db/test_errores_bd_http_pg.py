"""M3 — red de seguridad: lo que PostgreSQL rechaza responde 409/422, no 500.

Cada test provoca un tipo de error de BD a través de la app real (routers,
middleware y manejadores de ``app.main``) contra PostgreSQL real, y comprueba:

- el código HTTP (409 unique, 422 FK/CHECK/rango/formato/DataError);
- el formato de error del backend (``{"detail": {"code", "message"}}``) con un
  mensaje genérico en español;
- que el detalle técnico (nombre del constraint, tabla) NO viaja al cliente y
  SÍ queda en el log.

Los endpoints elegidos (paquetes, extras, paquete-tipos-evento) no tienen
validación explícita para estos casos; si algún día la tienen, cambia aquí el
endpoint por otro, no la aserción del manejador.

Cada test corre en una transacción que se revierte al final (mismo patrón que
``test_usuarios_sesion_db.py``). Un error de BD deja abortada esa transacción,
así que cada test hace una sola petición que falla.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL no definida (BD desechable)"
)


def _u(n: int) -> str:
    return f"a3300000-0000-0000-0000-{n:012d}"


SUCURSAL = _u(1)
SISTEMA = _u(2)
PAQUETE = _u(3)
TIPO_EVENTO = _u(4)
INEXISTENTE = _u(999)

_RUTA_SONDA = "/api/_prueba_m3/formato"


async def sembrar(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "INSERT INTO public.sucursales (id, nombre, clave) VALUES ($1, 'M3 Sucursal', 'M3S')",
        UUID(SUCURSAL),
    )
    await conn.execute(
        "INSERT INTO public.usuarios (id, email, password_hash, nombre_completo, rol) "
        "VALUES ($1, 'm3.sistema@woowkids.dev', 'x', 'M3 Sistema', 1)",
        UUID(SISTEMA),
    )
    await conn.execute(
        "INSERT INTO public.paquetes (id, sucursal_id, nombre, precio_base, min_invitados, "
        "max_invitados) VALUES ($1, $2, 'M3 Paquete', 1000, 5, 20)",
        UUID(PAQUETE),
        UUID(SUCURSAL),
    )
    await conn.execute(
        "INSERT INTO public.tipos_evento (id, sucursal_id, nombre) VALUES ($1, $2, 'M3 Tipo')",
        UUID(TIPO_EVENTO),
        UUID(SUCURSAL),
    )


def _headers() -> dict[str, str]:
    from app.core.security import create_access_token
    from app.services.permission_service import get_permissions

    token = create_access_token(
        payload={
            "sub": SISTEMA,
            "email": "m3.sistema@woowkids.dev",
            "role": "AdministradorSistema",
            "branch_id": None,
            "permissions": get_permissions("AdministradorSistema"),
        },
        expires_delta=timedelta(minutes=30),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def entorno() -> AsyncIterator[Any]:
    import httpx
    from app.core.database import get_db
    from app.main import app
    from app.services import permission_service
    from fastapi import Depends

    conn = await asyncpg.connect(TEST_DATABASE_URL)
    tx = conn.transaction()
    await tx.start()

    async def _get_db() -> AsyncIterator[asyncpg.Connection]:
        yield conn

    # Ruta de sonda montada en la app real solo durante el test: ningún
    # endpoint de negocio deja llegar un texto sin validar hasta un CAST de
    # PostgreSQL (InvalidTextRepresentation), así que se provoca aquí para
    # ejercer el manejador con la pila completa de la app.
    async def _sonda(valor: str, c: asyncpg.Connection = Depends(get_db)) -> dict[str, Any]:
        return {"n": await c.fetchval("SELECT $1::text::integer", valor)}

    app.add_api_route(_RUTA_SONDA, _sonda, methods=["GET"])
    ruta = app.router.routes[-1]
    try:
        await sembrar(conn)
        await permission_service.load_cache(conn)
        app.dependency_overrides[get_db] = _get_db
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        app.router.routes.remove(ruta)
        app.dependency_overrides.clear()
        await tx.rollback()
        await conn.close()


def _assert_error(
    resp: Any, status: int, code: str, filtrar: tuple[str, ...] = ()
) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    cuerpo = resp.json()
    assert set(cuerpo) == {"detail"}
    detail = cuerpo["detail"]
    assert detail["code"] == code
    assert detail["message"]
    for secreto in filtrar:
        assert secreto not in resp.text, f"{secreto!r} se filtró al cliente"
    return detail


async def test_unique_violation_responde_409(entorno: Any, caplog: Any) -> None:
    body = {"paquete_id": PAQUETE, "tipo_evento_id": TIPO_EVENTO}
    primero = await entorno.post("/api/paquete-tipos-evento", json=body, headers=_headers())
    assert primero.status_code == 201, primero.text

    with caplog.at_level(logging.WARNING, logger="mercury.errores_bd"):
        resp = await entorno.post("/api/paquete-tipos-evento", json=body, headers=_headers())

    detail = _assert_error(resp, 409, "REGISTRO_DUPLICADO", filtrar=("paquete_tipos_evento_pkey",))
    assert detail["message"] == "Ya existe un registro con esos datos."
    assert "paquete_tipos_evento_pkey" in caplog.text


async def test_foreign_key_inexistente_responde_422(entorno: Any, caplog: Any) -> None:
    body = {"paquete_id": INEXISTENTE, "tipo_evento_id": TIPO_EVENTO}
    with caplog.at_level(logging.WARNING, logger="mercury.errores_bd"):
        resp = await entorno.post("/api/paquete-tipos-evento", json=body, headers=_headers())

    _assert_error(
        resp,
        422,
        "REFERENCIA_INVALIDA",
        filtrar=("paquete_tipos_evento_paquete_id_fkey", "paquetes"),
    )
    assert "paquete_tipos_evento_paquete_id_fkey" in caplog.text


async def test_check_violation_responde_422(entorno: Any, caplog: Any) -> None:
    # Solo llega max_invitados (el schema no puede comparar con el min
    # guardado, 5): lo rechaza el CHECK chk_paquetes_rango_invitados.
    with caplog.at_level(logging.WARNING, logger="mercury.errores_bd"):
        resp = await entorno.patch(
            f"/api/paquetes/{PAQUETE}", json={"max_invitados": 2}, headers=_headers()
        )

    _assert_error(resp, 422, "VALOR_NO_PERMITIDO", filtrar=("chk_paquetes_rango_invitados",))
    assert "chk_paquetes_rango_invitados" in caplog.text


async def test_numeric_fuera_de_rango_responde_422(entorno: Any, caplog: Any) -> None:
    # extras.precio es numeric(10,2): 1e12 no cabe.
    body = {"nombre": "M3 Extra", "precio": "1000000000000", "sucursal_id": SUCURSAL}
    with caplog.at_level(logging.WARNING, logger="mercury.errores_bd"):
        resp = await entorno.post("/api/extras", json=body, headers=_headers())

    _assert_error(resp, 422, "VALOR_FUERA_DE_RANGO")
    assert "NumericValueOutOfRangeError" in caplog.text


async def test_entero_que_no_cabe_en_int4_responde_422(entorno: Any) -> None:
    # paquetes.min_invitados es integer: asyncpg rechaza el valor antes de
    # mandarlo (DataError del cliente, no del servidor).
    body = {
        "sucursal_id": SUCURSAL,
        "nombre": "M3 Paquete enorme",
        "precio_base": "100",
        "min_invitados": 3_000_000_000,
        "max_invitados": 3_000_000_001,
    }
    resp = await entorno.post("/api/paquetes", json=body, headers=_headers())

    _assert_error(resp, 422, "DATOS_INVALIDOS", filtrar=("int32", "query argument"))


async def test_formato_invalido_responde_422(entorno: Any, caplog: Any) -> None:
    with caplog.at_level(logging.WARNING, logger="mercury.errores_bd"):
        resp = await entorno.get(_RUTA_SONDA, params={"valor": "xx"}, headers=_headers())

    _assert_error(resp, 422, "FORMATO_INVALIDO", filtrar=("invalid input syntax",))
    assert "InvalidTextRepresentationError" in caplog.text
