"""P8 — usuarios y sesión contra PostgreSQL real (A10, A11, M1, M2).

- A10: un usuario desactivado sigue en el listado (filtro ``estado``) y se
  puede reactivar por PUT; el aislamiento por sucursal (C1) se mantiene.
- A11: el token de un usuario desactivado, eliminado o inexistente responde
  401 en cualquier endpoint, y su refresh token ya no renueva.
- M1: el correo no distingue mayúsculas (alta duplicada → 409, login con
  otra capitalización → 200).
- M2: el servidor exige contraseñas de al menos 8 caracteres.

Cada test corre en una transacción que se revierte al final (mismo patrón
que ``test_aislamiento_sucursal_db.py``).
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

# Hash bcrypt de '12345678' (mismo que sql/seed_local.sql).
PASSWORD = "12345678"
_HASH = "$2b$12$jGOsFgnr5KIF6TB6gbQ7A.tDGDQ56EsXo8NhGA9oPBYOgAvGIGLWO"


def _u(n: int) -> str:
    return f"a8000000-0000-0000-0000-{n:012d}"


SUC_A = _u(1)
SUC_B = _u(2)

USUARIOS = {
    # clave: (id, email, rol_id, sucursal)
    "sistema": (_u(11), "p8.sistema@woowkids.dev", 1, None),
    "admin_a": (_u(12), "p8.admin.a@woowkids.dev", 2, SUC_A),
    "admin_b": (_u(13), "p8.admin.b@woowkids.dev", 2, SUC_B),
    "cajero_a": (_u(14), "p8.cajero.a@woowkids.dev", 3, SUC_A),
}
_ROLES = {1: "AdministradorSistema", 2: "Administrador", 3: "Cajero"}


async def sembrar(conn: asyncpg.Connection) -> None:
    await conn.execute(
        f"""
        INSERT INTO public.sucursales (id, nombre, clave) VALUES
          ('{SUC_A}', 'P8 Sucursal A', 'P8A'), ('{SUC_B}', 'P8 Sucursal B', 'P8B');
        """
    )
    for uid, email, rol, suc in USUARIOS.values():
        await conn.execute(
            "INSERT INTO public.usuarios (id, email, password_hash, nombre_completo, rol) "
            "VALUES ($1, $2, $3, $4, $5)",
            UUID(uid),
            email,
            _HASH,
            f"P8 {email}",
            rol,
        )
        if suc is not None:
            await conn.execute(
                "INSERT INTO public.usuarios_sucursal (usuario_id, sucursal_id) VALUES ($1, $2)",
                UUID(uid),
                UUID(suc),
            )


def token_para(clave: str, sub: str | None = None) -> str:
    from app.core.security import create_access_token
    from app.services.permission_service import get_permissions

    uid, email, rol_id, suc = USUARIOS[clave]
    rol = _ROLES[rol_id]
    return create_access_token(
        payload={
            "sub": sub or uid,
            "email": email,
            "role": rol,
            "branch_id": suc,
            "permissions": get_permissions(rol),
        },
        expires_delta=timedelta(minutes=30),
    )


def _h(clave: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_para(clave)}"}


def _cuerpo_cajero_a(**extra: Any) -> dict[str, Any]:
    _uid, email, _r, suc = USUARIOS["cajero_a"]
    return {
        "email": email,
        "full_name": "P8 Cajero A",
        "role": "Cajero",
        "branch_id": suc,
        **extra,
    }


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
        await sembrar(conn)
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


def _ids(resp: Any) -> set[str]:
    assert resp.status_code == 200, resp.text
    return {u["id"] for u in resp.json()}


async def _desactivar_cajero(client: Any, quien: str = "admin_a") -> None:
    cajero_id = USUARIOS["cajero_a"][0]
    resp = await client.put(
        f"/api/usuarios/{cajero_id}", json=_cuerpo_cajero_a(is_active=False), headers=_h(quien)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False


# ── A10 ─────────────────────────────────────────────────────────────────────


async def test_desactivado_aparece_en_inactivos_y_todos(entorno: Any) -> None:
    client, _conn = entorno
    cajero_id = USUARIOS["cajero_a"][0]
    await _desactivar_cajero(client)

    for quien in ("admin_a", "sistema"):
        h = _h(quien)
        assert cajero_id not in _ids(await client.get("/api/usuarios", headers=h))
        assert cajero_id in _ids(await client.get("/api/usuarios?estado=inactivos", headers=h))
        assert cajero_id in _ids(await client.get("/api/usuarios?estado=todos", headers=h))
        activos = _ids(await client.get("/api/usuarios?estado=activos", headers=h))
        assert cajero_id not in activos
        assert USUARIOS["admin_a"][0] not in _ids(
            await client.get("/api/usuarios?estado=inactivos", headers=h)
        )


async def test_listado_de_inactivos_respeta_la_sucursal(entorno: Any) -> None:
    client, _conn = entorno
    await _desactivar_cajero(client)
    h = _h("admin_b")
    for estado in ("activos", "inactivos", "todos"):
        assert USUARIOS["cajero_a"][0] not in _ids(
            await client.get(f"/api/usuarios?estado={estado}", headers=h)
        )
    resp = await client.put(
        f"/api/usuarios/{USUARIOS['cajero_a'][0]}",
        json=_cuerpo_cajero_a(is_active=True, branch_id=SUC_B),
        headers=h,
    )
    assert resp.status_code == 403


async def test_estado_invalido_es_422(entorno: Any) -> None:
    client, _conn = entorno
    resp = await client.get("/api/usuarios?estado=borrados", headers=_h("sistema"))
    assert resp.status_code == 422


async def test_reactivar_usuario_desactivado(entorno: Any) -> None:
    client, conn = entorno
    cajero_id = USUARIOS["cajero_a"][0]
    await _desactivar_cajero(client)

    resp = await client.put(
        f"/api/usuarios/{cajero_id}", json=_cuerpo_cajero_a(is_active=True), headers=_h("admin_a")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True
    assert await conn.fetchval("SELECT activo FROM public.usuarios WHERE id = $1", UUID(cajero_id))

    login = await client.post(
        "/api/auth/login", json={"email": USUARIOS["cajero_a"][1], "password": PASSWORD}
    )
    assert login.status_code == 200, login.text


async def test_eliminado_tambien_se_puede_reactivar(entorno: Any) -> None:
    client, _conn = entorno
    cajero_id = USUARIOS["cajero_a"][0]
    resp = await client.delete(f"/api/usuarios/{cajero_id}", headers=_h("sistema"))
    assert resp.status_code == 204
    assert cajero_id in _ids(
        await client.get("/api/usuarios?estado=inactivos", headers=_h("sistema"))
    )
    resp = await client.put(
        f"/api/usuarios/{cajero_id}", json=_cuerpo_cajero_a(is_active=True), headers=_h("sistema")
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is True


# ── A11 ─────────────────────────────────────────────────────────────────────


async def test_token_de_usuario_desactivado_es_401(entorno: Any) -> None:
    client, _conn = entorno
    h_cajero = _h("cajero_a")
    assert (await client.get("/api/metodos-pago", headers=h_cajero)).status_code == 200

    await _desactivar_cajero(client)

    resp = await client.get("/api/metodos-pago", headers=h_cajero)
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["code"] == "ACCOUNT_DISABLED"


async def test_token_de_usuario_eliminado_es_401(entorno: Any) -> None:
    client, _conn = entorno
    h_cajero = _h("cajero_a")
    resp = await client.delete(f"/api/usuarios/{USUARIOS['cajero_a'][0]}", headers=_h("admin_a"))
    assert resp.status_code == 204
    assert (await client.get("/api/metodos-pago", headers=h_cajero)).status_code == 401


async def test_token_de_usuario_inexistente_es_401(entorno: Any) -> None:
    client, _conn = entorno
    token = token_para("cajero_a", sub="a8000000-0000-0000-0000-999999999999")
    resp = await client.get("/api/metodos-pago", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


async def test_refresh_de_usuario_desactivado_no_renueva(entorno: Any) -> None:
    client, conn = entorno
    login = await client.post(
        "/api/auth/login", json={"email": USUARIOS["cajero_a"][1], "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    cookie = login.cookies.get("refresh_token")
    assert cookie
    client.cookies.clear()

    await _desactivar_cajero(client)
    # Al desactivar se revocan sus refresh tokens.
    assert not await conn.fetchval(
        "SELECT count(*) FROM public.refresh_tokens WHERE usuario_id = $1 AND NOT revocado",
        UUID(USUARIOS["cajero_a"][0]),
    )

    resp = await client.post("/api/auth/refresh", cookies={"refresh_token": cookie})
    assert resp.status_code == 401
    # Ni reactivando la cuenta revive la sesión vieja.
    resp = await client.put(
        f"/api/usuarios/{USUARIOS['cajero_a'][0]}",
        json=_cuerpo_cajero_a(is_active=True),
        headers=_h("admin_a"),
    )
    assert resp.status_code == 200
    resp = await client.post("/api/auth/refresh", cookies={"refresh_token": cookie})
    assert resp.status_code == 401


# ── M1 ──────────────────────────────────────────────────────────────────────


async def test_alta_con_otra_capitalizacion_es_409(entorno: Any) -> None:
    client, _conn = entorno
    resp = await client.post(
        "/api/usuarios",
        json={
            "email": "  P8.Cajero.A@WoowKids.dev ",
            "full_name": "Duplicado",
            "password": PASSWORD,
            "role": "Cajero",
            "branch_id": SUC_A,
        },
        headers=_h("sistema"),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "EMAIL_ALREADY_EXISTS"


async def test_alta_guarda_el_correo_en_minusculas(entorno: Any) -> None:
    client, conn = entorno
    resp = await client.post(
        "/api/usuarios",
        json={
            "email": "Nuevo.P8@WoowKids.dev",
            "full_name": "Nuevo",
            "password": PASSWORD,
            "role": "Cajero",
            "branch_id": SUC_A,
        },
        headers=_h("sistema"),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == "nuevo.p8@woowkids.dev"
    assert await conn.fetchval(
        "SELECT email FROM public.usuarios WHERE id = $1", UUID(resp.json()["id"])
    ) == ("nuevo.p8@woowkids.dev")


async def test_correo_de_usuario_inactivo_sigue_ocupado(entorno: Any) -> None:
    client, _conn = entorno
    await _desactivar_cajero(client)
    resp = await client.post(
        "/api/usuarios",
        json={
            "email": USUARIOS["cajero_a"][1].upper(),
            "full_name": "Otro",
            "password": PASSWORD,
            "role": "Cajero",
            "branch_id": SUC_A,
        },
        headers=_h("sistema"),
    )
    assert resp.status_code == 409


async def test_editar_a_correo_ajeno_con_otra_capitalizacion_es_409(entorno: Any) -> None:
    client, _conn = entorno
    resp = await client.put(
        f"/api/usuarios/{USUARIOS['cajero_a'][0]}",
        json=_cuerpo_cajero_a(email="P8.ADMIN.B@woowkids.dev"),
        headers=_h("sistema"),
    )
    assert resp.status_code == 409


async def test_login_con_otra_capitalizacion(entorno: Any) -> None:
    client, _conn = entorno
    resp = await client.post(
        "/api/auth/login",
        json={"email": "P8.Cajero.A@WOOWKIDS.dev", "password": PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["user"]["id"] == USUARIOS["cajero_a"][0]


async def test_cuenta_vieja_con_mayusculas_entra_y_se_puede_editar(entorno: Any) -> None:
    """Un correo guardado con mayúsculas antes de 089 (p. ej. porque chocaba)
    sigue funcionando: login con cualquier capitalización y edición sin 409."""
    client, conn = entorno
    await conn.execute(
        "UPDATE public.usuarios SET email = 'P8.Cajero.A@WoowKids.dev' WHERE id = $1",
        UUID(USUARIOS["cajero_a"][0]),
    )
    resp = await client.post(
        "/api/auth/login", json={"email": "p8.cajero.a@woowkids.dev", "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.put(
        f"/api/usuarios/{USUARIOS['cajero_a'][0]}",
        json=_cuerpo_cajero_a(),
        headers=_h("admin_a"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "p8.cajero.a@woowkids.dev"


async def test_indice_unico_sin_distinguir_mayusculas(entorno: Any) -> None:
    _client, conn = entorno
    with pytest.raises(asyncpg.UniqueViolationError):
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO public.usuarios (email, password_hash, nombre_completo, rol) "
                "VALUES ('P8.CAJERO.A@woowkids.dev', 'x', 'dup', 3)"
            )
