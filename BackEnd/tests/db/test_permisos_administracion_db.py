"""Q5 — permisos, alcance por sucursal y administración, contra PostgreSQL real.

- M19: horarios por sucursal (globales = sucursal_id NULL).
- M20: desactivar por PATCH exige el mismo permiso que DELETE.

Cada test corre en una transacción que se revierte al final (mismo patrón
que ``test_aislamiento_sucursal_db.py``).
"""

from __future__ import annotations

import json
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
    return f"a5000000-0000-0000-0000-{n:012d}"


SUC_A = _u(1)
SUC_B = _u(2)
ROL_INVENTARIO = 905  # rol personalizado "Supervisor de inventario"

USUARIOS = {
    # clave: (id, email, rol_id, sucursal)
    "sistema": (_u(11), "q5.sistema@woowkids.dev", 1, None),
    "admin_a": (_u(12), "q5.admin.a@woowkids.dev", 2, SUC_A),
    "admin_b": (_u(13), "q5.admin.b@woowkids.dev", 2, SUC_B),
    "cajero_a": (_u(14), "q5.cajero.a@woowkids.dev", 3, SUC_A),
    "atencion_a": (_u(15), "q5.atencion.a@woowkids.dev", 5, SUC_A),
    "inventario_a": (_u(16), "q5.inventario.a@woowkids.dev", ROL_INVENTARIO, SUC_A),
}
_ROLES = {
    1: "AdministradorSistema",
    2: "Administrador",
    3: "Cajero",
    5: "Personal de atención de niños",
    ROL_INVENTARIO: "Q5 Supervisor de inventario",
}

IDS = {
    "global": _u(101),
    "horario_a": _u(102),
    "horario_b": _u(103),
    "caja_a": _u(104),
    "caja_b": _u(105),
    "producto_a": _u(106),
    "insumo_a": _u(107),
    "proveedor_a": _u(108),
}


async def sembrar(conn: asyncpg.Connection) -> None:
    unidad = await conn.fetchval("SELECT id FROM public.unidades_medida ORDER BY codigo LIMIT 1")
    await conn.execute(
        f"""
        INSERT INTO public.sucursales (id, nombre, clave) VALUES
          ('{SUC_A}', 'Q5 Sucursal A', 'Q5A'), ('{SUC_B}', 'Q5 Sucursal B', 'Q5B');
        INSERT INTO public.roles (id, nombre, descripcion, activo)
          VALUES ({ROL_INVENTARIO}, '{_ROLES[ROL_INVENTARIO]}', 'Prueba Q5', TRUE);
        INSERT INTO public.rol_permisos (rol_id, permiso_id)
          SELECT {ROL_INVENTARIO}, id FROM public.permisos
          WHERE codigo IN ('inventario:ver', 'inventario:gestionar_insumos',
                           'inventario:gestionar_proveedores');
        INSERT INTO public.turnos (id, nombre, hora_inicio, hora_fin, sucursal_id) VALUES
          ('{IDS["global"]}', 'Q5 Global', '08:00', '14:00', NULL),
          ('{IDS["horario_a"]}', 'Q5 Matutino A', '08:00', '14:00', '{SUC_A}'),
          ('{IDS["horario_b"]}', 'Q5 Matutino B', '08:00', '14:00', '{SUC_B}');
        INSERT INTO public.cajas (id, sucursal_id, codigo, nombre, numero) VALUES
          ('{IDS["caja_a"]}', '{SUC_A}', 'Q5-A', 'Q5 Caja A', 51),
          ('{IDS["caja_b"]}', '{SUC_B}', 'Q5-B', 'Q5 Caja B', 52);
        INSERT INTO public.productos (id, sucursal_id, nombre, precio_unitario, tipo)
          VALUES ('{IDS["producto_a"]}', '{SUC_A}', 'Q5 Pizza A', 95, 'A');
        INSERT INTO public.insumos (id, sucursal_id, nombre, unidad_base_id, unidad_compra_id)
          VALUES ('{IDS["insumo_a"]}', '{SUC_A}', 'Q5 Leche A', '{unidad}', '{unidad}');
        INSERT INTO public.proveedores (id, sucursal_id, nombre)
          VALUES ('{IDS["proveedor_a"]}', '{SUC_A}', 'Q5 Proveedor A');
        """
    )
    for uid, email, rol, suc in USUARIOS.values():
        await conn.execute(
            "INSERT INTO public.usuarios (id, email, password_hash, nombre_completo, rol) "
            "VALUES ($1, $2, $3, $4, $5)",
            UUID(uid),
            email,
            _HASH,
            f"Q5 {email}",
            rol,
        )
        if suc is not None:
            await conn.execute(
                "INSERT INTO public.usuarios_sucursal (usuario_id, sucursal_id) VALUES ($1, $2)",
                UUID(uid),
                UUID(suc),
            )


def token_para(clave: str) -> str:
    from app.core.security import create_access_token
    from app.services.permission_service import get_permissions

    uid, email, rol_id, suc = USUARIOS[clave]
    rol = _ROLES[rol_id]
    return create_access_token(
        payload={
            "sub": uid,
            "email": email,
            "role": rol,
            "branch_id": suc,
            "permissions": get_permissions(rol),
        },
        expires_delta=timedelta(minutes=30),
    )


def _h(clave: str, vista: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token_para(clave)}"}
    if vista is not None:
        headers["X-Sucursal-Vista"] = vista
    return headers


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
        # El caché de permisos es global al proceso: no dejar el rol de prueba.
        reconectar = await asyncpg.connect(TEST_DATABASE_URL)
        try:
            await permission_service.load_cache(reconectar)
        finally:
            await reconectar.close()


def _ids(resp: Any) -> set[str]:
    return {str(item["id"]) for item in resp.json()}


# ── M19: horarios por sucursal ─────────────────────────────────────────────


async def test_horarios_listado_muestra_los_de_la_sucursal_y_los_globales(
    entorno: Any,
) -> None:
    client, _conn = entorno
    resp = await client.get("/api/horarios", headers=_h("admin_a"))
    assert resp.status_code == 200, resp.text
    ids = _ids(resp)
    assert {IDS["global"], IDS["horario_a"]} <= ids
    assert IDS["horario_b"] not in ids
    por_id = {h["id"]: h for h in resp.json()}
    assert por_id[IDS["global"]]["sucursal_id"] is None
    assert por_id[IDS["horario_a"]]["sucursal_id"] == SUC_A


async def test_apertura_de_caja_solo_ofrece_horarios_de_la_sucursal_y_globales(
    entorno: Any,
) -> None:
    client, _conn = entorno
    resp = await client.get("/api/turnos-caja/turnos", headers=_h("cajero_a"))
    assert resp.status_code == 200, resp.text
    ids = _ids(resp)
    assert {IDS["global"], IDS["horario_a"]} <= ids
    assert IDS["horario_b"] not in ids


async def test_sistema_ve_todos_los_horarios_y_filtra_con_el_selector(entorno: Any) -> None:
    client, _conn = entorno
    todas = _ids(await client.get("/api/horarios", headers=_h("sistema")))
    assert {IDS["global"], IDS["horario_a"], IDS["horario_b"]} <= todas
    en_b = _ids(await client.get("/api/horarios", headers=_h("sistema", vista=SUC_B)))
    assert IDS["horario_a"] not in en_b
    assert {IDS["global"], IDS["horario_b"]} <= en_b


async def test_admin_crea_horario_en_su_sucursal_aunque_otra_tenga_el_mismo_nombre(
    entorno: Any,
) -> None:
    client, conn = entorno
    resp = await client.post(
        "/api/horarios",
        json={"nombre": "Q5 Matutino A", "hora_inicio": "09:00", "hora_fin": "15:00"},
        headers=_h("admin_b"),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["sucursal_id"] == SUC_B
    sucursal = await conn.fetchval(
        "SELECT sucursal_id FROM public.turnos WHERE id = $1", UUID(resp.json()["id"])
    )
    assert str(sucursal) == SUC_B
    # El de A no aparece en B (y viceversa).
    assert resp.json()["id"] not in _ids(await client.get("/api/horarios", headers=_h("admin_a")))


async def test_horario_de_sucursal_no_puede_llamarse_como_uno_global(entorno: Any) -> None:
    client, _conn = entorno
    resp = await client.post(
        "/api/horarios",
        json={"nombre": "Q5 Global", "hora_inicio": "09:00", "hora_fin": "15:00"},
        headers=_h("admin_a"),
    )
    assert resp.status_code == 409, resp.text


async def test_admin_edita_los_suyos_pero_no_los_globales_ni_los_de_otra(entorno: Any) -> None:
    client, conn = entorno
    propio = await client.patch(
        f"/api/horarios/{IDS['horario_a']}", json={"hora_fin": "15:00"}, headers=_h("admin_a")
    )
    assert propio.status_code == 200, propio.text
    assert propio.json()["hora_fin"] == "15:00"

    glob = await client.patch(
        f"/api/horarios/{IDS['global']}", json={"nombre": "Hackeado"}, headers=_h("admin_a")
    )
    assert glob.status_code == 403, glob.text
    otra = await client.delete(f"/api/horarios/{IDS['horario_b']}", headers=_h("admin_a"))
    assert otra.status_code == 404, otra.text

    assert await conn.fetchval(
        "SELECT nombre FROM public.turnos WHERE id = $1", UUID(IDS["global"])
    ) == ("Q5 Global")
    assert await conn.fetchval(
        "SELECT activo FROM public.turnos WHERE id = $1", UUID(IDS["horario_b"])
    )


async def test_sistema_edita_un_horario_global(entorno: Any) -> None:
    client, _conn = entorno
    resp = await client.patch(
        f"/api/horarios/{IDS['global']}", json={"hora_fin": "13:00"}, headers=_h("sistema")
    )
    assert resp.status_code == 200, resp.text


async def test_no_se_abre_caja_con_un_horario_de_otra_sucursal(entorno: Any) -> None:
    client, conn = entorno
    payload = {"fondo_inicial": 500, "caja_id": IDS["caja_a"], "pin": PASSWORD}
    resp = await client.post(
        "/api/turnos-caja/abrir",
        json={**payload, "turno_id": IDS["horario_b"]},
        headers=_h("cajero_a"),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "TURNO_INVALIDO"
    inexistente = await client.post(
        "/api/turnos-caja/abrir",
        json={**payload, "turno_id": _u(999)},
        headers=_h("cajero_a"),
    )
    assert inexistente.status_code == 422, inexistente.text

    resp = await client.post(
        "/api/turnos-caja/abrir",
        json={**payload, "turno_id": IDS["horario_a"]},
        headers=_h("cajero_a"),
    )
    assert resp.status_code == 201, resp.text
    assert await conn.fetchval(
        "SELECT count(*) FROM public.apertura_caja WHERE caja_id = $1", UUID(IDS["caja_a"])
    )


# ── M20: desactivar por PATCH = eliminar ───────────────────────────────────

_TABLAS = {"productos", "insumos", "proveedores"}


async def _activo(conn: asyncpg.Connection, tabla: str, rid: str) -> bool:
    assert tabla in _TABLAS
    sql = f"SELECT activo FROM public.{tabla} WHERE id = $1"
    return bool(await conn.fetchval(sql, UUID(rid)))


async def test_admin_sin_permiso_de_eliminar_no_desactiva_productos_por_patch(
    entorno: Any,
) -> None:
    """El rol Administrador tiene gestionar_productos pero no eliminar_producto:
    DELETE daba 403 y PATCH activo=false lo desactivaba igual."""
    client, conn = entorno
    url = f"/api/productos/{IDS['producto_a']}"
    borrar = await client.delete(url, headers=_h("admin_a"))
    assert borrar.status_code == 403, borrar.text
    desactivar = await client.patch(
        url, data={"payload": json.dumps({"activo": False})}, headers=_h("admin_a")
    )
    assert desactivar.status_code == 403, desactivar.text
    assert await _activo(conn, "productos", IDS["producto_a"])
    # Editar sigue permitido con gestionar_productos.
    editar = await client.patch(
        url, data={"payload": json.dumps({"nombre": "Q5 Pizza grande"})}, headers=_h("admin_a")
    )
    assert editar.status_code == 200, editar.text


async def test_sin_permiso_de_eliminar_no_se_desactivan_insumos_ni_proveedores(
    entorno: Any,
) -> None:
    """Rol con gestionar_insumos/gestionar_proveedores y sin eliminar_*."""
    client, conn = entorno
    for tabla, rid in (("insumos", IDS["insumo_a"]), ("proveedores", IDS["proveedor_a"])):
        url = f"/api/{tabla}/{rid}"
        assert (await client.delete(url, headers=_h("inventario_a"))).status_code == 403
        resp = await client.patch(url, json={"activo": False}, headers=_h("inventario_a"))
        assert resp.status_code == 403, (tabla, resp.text)
        assert await _activo(conn, tabla, rid), tabla
        resp = await client.patch(url, json={"nombre": f"Q5 {tabla}"}, headers=_h("inventario_a"))
        assert resp.status_code == 200, (tabla, resp.text)


async def test_con_permiso_de_eliminar_si_se_desactiva_por_patch(entorno: Any) -> None:
    client, conn = entorno
    url = f"/api/insumos/{IDS['insumo_a']}"
    resp = await client.patch(url, json={"activo": False}, headers=_h("admin_a"))
    assert resp.status_code == 200, resp.text
    assert not await _activo(conn, "insumos", IDS["insumo_a"])
    # Reactivar no es eliminar: basta con gestionar.
    resp = await client.patch(url, json={"activo": True}, headers=_h("inventario_a"))
    assert resp.status_code == 200, resp.text


# ── M3: sucursal inexistente al dar de alta/editar un usuario ──────────────

_SUCURSAL_INEXISTENTE = "00000000-0000-0000-0000-000000000000"


async def test_alta_de_usuario_con_sucursal_inexistente_da_422(entorno: Any) -> None:
    client, conn = entorno
    resp = await client.post(
        "/api/usuarios",
        json={
            "email": "q5.nuevo@woowkids.dev",
            "full_name": "Q5 Nuevo",
            "password": PASSWORD,
            "role": "Cajero",
            "branch_id": _SUCURSAL_INEXISTENTE,
        },
        headers=_h("sistema"),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "SUCURSAL_NO_ENCONTRADA"
    assert not await conn.fetchval(
        "SELECT count(*) FROM public.usuarios WHERE email = 'q5.nuevo@woowkids.dev'"
    )


async def test_editar_usuario_a_una_sucursal_inexistente_da_422(entorno: Any) -> None:
    client, conn = entorno
    uid, email, _rol, _suc = USUARIOS["cajero_a"]
    resp = await client.put(
        f"/api/usuarios/{uid}",
        json={
            "email": email,
            "full_name": "Q5 Cajero A",
            "role": "Cajero",
            "branch_id": _SUCURSAL_INEXISTENTE,
        },
        headers=_h("sistema"),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "SUCURSAL_NO_ENCONTRADA"
    sucursal = await conn.fetchval(
        "SELECT sucursal_id FROM public.usuarios_sucursal WHERE usuario_id = $1 AND activo",
        UUID(uid),
    )
    assert str(sucursal) == SUC_A
