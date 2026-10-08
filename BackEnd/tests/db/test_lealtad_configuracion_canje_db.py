"""Canje de puntos desde caja, contra PostgreSQL real.

- Un Cajero (permisos reales del rol sembrado en el maestro) lee el valor del
  punto y el mínimo de canje de SU sucursal por GET /lealtad/configuracion/canje
  y no puede leer los de otra (403), ni la configuración completa.
- El servidor sigue validando el mínimo de canje al cobrar: con saldo por
  debajo del mínimo, redimir_puntos rechaza y no toca los lotes.

Requiere ``TEST_DATABASE_URL`` (BD desechable con ``sql/schema_maestro.sql``).
Cada test corre en una transacción que se revierte al final.
"""

from __future__ import annotations

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
    return f"a6000000-0000-0000-0000-{n:012d}"


SUC_A = _u(1)
SUC_B = _u(2)
CAJERO_A = _u(11)
CELULAR = "3300000066"


async def _sembrar(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        INSERT INTO public.sucursales (id, nombre, clave) VALUES
          ('{SUC_A}', 'Lealtad Sucursal A', 'LEAA'), ('{SUC_B}', 'Lealtad Sucursal B', 'LEAB');
        INSERT INTO public.usuarios (id, email, password_hash, nombre_completo, rol)
          VALUES ('{CAJERO_A}', 'lealtad.cajero.a@woowkids.dev', 'x', 'Lealtad Cajero A', 3);
        INSERT INTO public.usuarios_sucursal (usuario_id, sucursal_id)
          VALUES ('{CAJERO_A}', '{SUC_A}');
        INSERT INTO public.configuracion_lealtad
            (sucursal_id, dias_caducidad, valor_punto, minimo_canje, porcentaje_retorno)
          VALUES ('{SUC_A}', 30, 0.50, 50, 5), ('{SUC_B}', 30, 2.00, 10, 7);
        """
    )


def _token_cajero() -> str:
    from app.core.security import create_access_token
    from app.services.permission_service import get_permissions

    return create_access_token(
        payload={
            "sub": CAJERO_A,
            "email": "lealtad.cajero.a@woowkids.dev",
            "role": "Cajero",
            "branch_id": SUC_A,
            "permissions": get_permissions("Cajero"),
        },
        expires_delta=timedelta(minutes=30),
    )


@pytest_asyncio.fixture
async def entorno() -> AsyncIterator[Any]:
    import httpx
    from app.core.database import get_db
    from app.main import app
    from app.services import permission_service

    conn = await asyncpg.connect(TEST_DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    try:
        await _sembrar(conn)
        await permission_service.load_cache(conn)

        async def _get_db() -> AsyncIterator[asyncpg.Connection]:
            yield conn

        app.dependency_overrides[get_db] = _get_db
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, conn
    finally:
        app.dependency_overrides.clear()
        await tx.rollback()
        await conn.close()


async def test_cajero_lee_la_configuracion_de_canje_de_su_sucursal(entorno: Any) -> None:
    client, _conn = entorno
    headers = {"Authorization": f"Bearer {_token_cajero()}"}

    resp = await client.get("/api/lealtad/configuracion/canje", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "sucursal_id": SUC_A,
        "activo": True,
        "valor_punto": 0.5,
        "minimo_canje": 50,
    }

    resp = await client.get(
        f"/api/lealtad/configuracion/canje?sucursal_id={SUC_A}", headers=headers
    )
    assert resp.status_code == 200, resp.text


async def test_cajero_no_lee_la_de_otra_sucursal(entorno: Any) -> None:
    client, _conn = entorno
    headers = {"Authorization": f"Bearer {_token_cajero()}"}
    resp = await client.get(
        f"/api/lealtad/configuracion/canje?sucursal_id={SUC_B}", headers=headers
    )
    assert resp.status_code == 403, resp.text
    assert "2.0" not in resp.text


async def test_cajero_sigue_sin_acceso_a_la_configuracion_completa(entorno: Any) -> None:
    client, conn = entorno
    headers = {"Authorization": f"Bearer {_token_cajero()}"}
    assert (await client.get("/api/lealtad/configuracion", headers=headers)).status_code == 403
    resp = await client.put(
        "/api/lealtad/configuracion",
        json={"porcentaje_retorno": 99, "dias_caducidad": 1, "valor_punto": 100},
        headers=headers,
    )
    assert resp.status_code == 403
    valor = await conn.fetchval(
        "SELECT valor_punto FROM public.configuracion_lealtad WHERE sucursal_id = $1",
        UUID(SUC_A),
    )
    assert float(valor) == 0.5


async def test_el_servidor_valida_el_minimo_de_canje_al_cobrar(entorno: Any) -> None:
    from app.exceptions import DatosInvalidos
    from app.services import lealtad_service

    _client, conn = entorno
    lote_id = await conn.fetchval(
        """
        INSERT INTO public.lotes_puntos
            (sucursal_id, celular, puntos_otorgados, puntos_disponibles,
             fecha_caducidad, creado_por, registro_id)
        VALUES ($1, $2, 6, 6, NOW() + INTERVAL '30 days', $3, NULL)
        RETURNING id
        """,
        UUID(SUC_A),
        CELULAR,
        UUID(CAJERO_A),
    )

    with pytest.raises(DatosInvalidos, match="Mínimo para canjear: 50"):
        await lealtad_service.redimir_puntos(conn, UUID(SUC_A), CELULAR, 6, None, UUID(CAJERO_A))

    disponibles = await conn.fetchval(
        "SELECT puntos_disponibles FROM public.lotes_puntos WHERE id = $1", lote_id
    )
    assert disponibles == 6
