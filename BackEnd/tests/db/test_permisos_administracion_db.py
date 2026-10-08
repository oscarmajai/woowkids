"""Permisos, alcance por sucursal y administración, contra PostgreSQL real.

- Horarios por sucursal (globales = sucursal_id NULL).
- Desactivar por PATCH exige el mismo permiso que DELETE.
- Usuario con sucursal inexistente → 422.
- Activar métodos de pago con la sucursal elegida.
- tiene_pin en login y refresh.
- Cajas desde "Todas las sucursales".
- Historial de ventas del AdministradorSistema.
- Lectura de /productos/catalogo y /productos/admin por rol.

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
    "sistema": (_u(11), "permisos.sistema@woowkids.dev", 1, None),
    "admin_a": (_u(12), "permisos.admin.a@woowkids.dev", 2, SUC_A),
    "admin_b": (_u(13), "permisos.admin.b@woowkids.dev", 2, SUC_B),
    "cajero_a": (_u(14), "permisos.cajero.a@woowkids.dev", 3, SUC_A),
    "atencion_a": (_u(15), "permisos.atencion.a@woowkids.dev", 5, SUC_A),
    "inventario_a": (_u(16), "permisos.inventario.a@woowkids.dev", ROL_INVENTARIO, SUC_A),
}
_ROLES = {
    1: "AdministradorSistema",
    2: "Administrador",
    3: "Cajero",
    5: "Personal de atención de niños",
    ROL_INVENTARIO: "Permisos Supervisor de inventario",
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
          ('{SUC_A}', 'Permisos Sucursal A', 'PERA'), ('{SUC_B}', 'Permisos Sucursal B', 'PERB');
        INSERT INTO public.roles (id, nombre, descripcion, activo)
          VALUES ({ROL_INVENTARIO}, '{_ROLES[ROL_INVENTARIO]}', 'Prueba de permisos', TRUE);
        INSERT INTO public.rol_permisos (rol_id, permiso_id)
          SELECT {ROL_INVENTARIO}, id FROM public.permisos
          WHERE codigo IN ('inventario:ver', 'inventario:gestionar_insumos',
                           'inventario:gestionar_proveedores');
        INSERT INTO public.turnos (id, nombre, hora_inicio, hora_fin, sucursal_id) VALUES
          ('{IDS["global"]}', 'Permisos Global', '08:00', '14:00', NULL),
          ('{IDS["horario_a"]}', 'Permisos Matutino A', '08:00', '14:00', '{SUC_A}'),
          ('{IDS["horario_b"]}', 'Permisos Matutino B', '08:00', '14:00', '{SUC_B}');
        INSERT INTO public.cajas (id, sucursal_id, codigo, nombre, numero) VALUES
          ('{IDS["caja_a"]}', '{SUC_A}', 'PER-A', 'Permisos Caja A', 51),
          ('{IDS["caja_b"]}', '{SUC_B}', 'PER-B', 'Permisos Caja B', 52);
        INSERT INTO public.productos (id, sucursal_id, nombre, precio_unitario, tipo)
          VALUES ('{IDS["producto_a"]}', '{SUC_A}', 'Permisos Pizza A', 95, 'A');
        INSERT INTO public.insumos (id, sucursal_id, nombre, unidad_base_id, unidad_compra_id)
          VALUES ('{IDS["insumo_a"]}', '{SUC_A}', 'Permisos Leche A', '{unidad}', '{unidad}');
        INSERT INTO public.proveedores (id, sucursal_id, nombre)
          VALUES ('{IDS["proveedor_a"]}', '{SUC_A}', 'Permisos Proveedor A');
        """
    )
    for uid, email, rol, suc in USUARIOS.values():
        await conn.execute(
            "INSERT INTO public.usuarios (id, email, password_hash, nombre_completo, rol) "
            "VALUES ($1, $2, $3, $4, $5)",
            UUID(uid),
            email,
            _HASH,
            f"Permisos {email}",
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


# ── Horarios por sucursal ──────────────────────────────────────────────────


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
        json={"nombre": "Permisos Matutino A", "hora_inicio": "09:00", "hora_fin": "15:00"},
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
        json={"nombre": "Permisos Global", "hora_inicio": "09:00", "hora_fin": "15:00"},
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
    ) == ("Permisos Global")
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


# ── Desactivar por PATCH = eliminar ────────────────────────────────────────

_TABLAS = {"productos", "insumos", "proveedores"}


async def _activo(conn: asyncpg.Connection, tabla: str, rid: str) -> bool:
    assert tabla in _TABLAS
    sql = f"SELECT activo FROM public.{tabla} WHERE id = $1"
    return bool(await conn.fetchval(sql, UUID(rid)))


async def test_admin_desactiva_productos_con_eliminar_producto(entorno: Any) -> None:
    """Desde la migración 101 el Administrador tiene inventario:eliminar_producto
    (todos los permisos salvo los del sistema), así que exigir en el PATCH el
    permiso de DELETE no le quita la forma de desactivar productos."""
    client, conn = entorno
    url = f"/api/productos/{IDS['producto_a']}"
    editar = await client.patch(
        url,
        data={"payload": json.dumps({"nombre": "Permisos Pizza grande"})},
        headers=_h("admin_a"),
    )
    assert editar.status_code == 200, editar.text
    desactivar = await client.patch(
        url, data={"payload": json.dumps({"activo": False})}, headers=_h("admin_a")
    )
    assert desactivar.status_code == 200, desactivar.text
    assert not await _activo(conn, "productos", IDS["producto_a"])


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
        resp = await client.patch(
            url, json={"nombre": f"Permisos {tabla}"}, headers=_h("inventario_a")
        )
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


# ── Sucursal inexistente al dar de alta/editar un usuario ──────────────────

_SUCURSAL_INEXISTENTE = "00000000-0000-0000-0000-000000000000"


async def test_alta_de_usuario_con_sucursal_inexistente_da_422(entorno: Any) -> None:
    client, conn = entorno
    resp = await client.post(
        "/api/usuarios",
        json={
            "email": "permisos.nuevo@woowkids.dev",
            "full_name": "Permisos Nuevo",
            "password": PASSWORD,
            "role": "Cajero",
            "branch_id": _SUCURSAL_INEXISTENTE,
        },
        headers=_h("sistema"),
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "SUCURSAL_NO_ENCONTRADA"
    assert not await conn.fetchval(
        "SELECT count(*) FROM public.usuarios WHERE email = 'permisos.nuevo@woowkids.dev'"
    )


async def test_editar_usuario_a_una_sucursal_inexistente_da_422(entorno: Any) -> None:
    client, conn = entorno
    uid, email, _rol, _suc = USUARIOS["cajero_a"]
    resp = await client.put(
        f"/api/usuarios/{uid}",
        json={
            "email": email,
            "full_name": "Permisos Cajero A",
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


# ── Activar métodos de pago desde "Todas las sucursales" ───────────────────


async def _activo_en(conn: asyncpg.Connection, metodo: UUID, sucursal: str) -> bool | None:
    activo: bool | None = await conn.fetchval(
        "SELECT activo FROM public.sucursal_metodos_pago "
        "WHERE metodo_pago_id = $1 AND sucursal_id = $2",
        metodo,
        UUID(sucursal),
    )
    return activo


async def test_activacion_de_metodo_de_pago_por_sucursal(entorno: Any) -> None:
    client, conn = entorno
    metodo = await conn.fetchval("SELECT id FROM public.metodos_pago WHERE nombre = 'Tarjeta'")
    url = f"/api/metodos-pago/{metodo}/activacion"

    # Sistema sin sucursal elegida: 422 con mensaje claro (antes, un texto suelto).
    resp = await client.patch(url, json={"activo": False}, headers=_h("sistema"))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["code"] == "SUCURSAL_REQUERIDA"

    # Sistema con la sucursal explícita o con el selector.
    resp = await client.patch(
        f"{url}?sucursal_id={SUC_A}", json={"activo": False}, headers=_h("sistema")
    )
    assert resp.status_code == 200, resp.text
    assert await _activo_en(conn, metodo, SUC_A) is False
    resp = await client.patch(url, json={"activo": False}, headers=_h("sistema", vista=SUC_B))
    assert resp.status_code == 200, resp.text
    assert await _activo_en(conn, metodo, SUC_B) is False

    # Rol con sucursal fija: la suya sí, otra no.
    resp = await client.patch(
        f"{url}?sucursal_id={SUC_A}", json={"activo": True}, headers=_h("admin_b")
    )
    assert resp.status_code == 403, resp.text
    assert await _activo_en(conn, metodo, SUC_A) is False
    resp = await client.patch(url, json={"activo": True}, headers=_h("admin_a"))
    assert resp.status_code == 200, resp.text
    assert await _activo_en(conn, metodo, SUC_A) is True


# ── tiene_pin en login y refresh ────────────────────────────────────────────


async def test_login_y_refresh_informan_si_el_usuario_tiene_pin(entorno: Any) -> None:
    from app.core.security import hash_password

    client, conn = entorno
    uid, email, _rol, _suc = USUARIOS["cajero_a"]
    await conn.execute(
        "UPDATE public.usuarios SET pin_hash = $1 WHERE id = $2", hash_password("4321"), UUID(uid)
    )

    login = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert login.status_code == 200, login.text
    assert login.json()["user"]["tiene_pin"] is True

    refresh = await client.post(
        "/api/auth/refresh", json={"refreshToken": login.json()["refresh_token"]}
    )
    assert refresh.status_code == 200, refresh.text
    assert refresh.json()["user"]["tiene_pin"] is True

    _uid, email_sin_pin, _r, _s = USUARIOS["atencion_a"]
    sin_pin = await client.post(
        "/api/auth/login", json={"email": email_sin_pin, "password": PASSWORD}
    )
    assert sin_pin.status_code == 200, sin_pin.text
    assert sin_pin.json()["user"]["tiene_pin"] is False


# ── Cajas desde "Todas las sucursales" ─────────────────────────────────────


async def test_sistema_lista_y_edita_cajas_sin_sucursal_elegida(entorno: Any) -> None:
    client, conn = entorno
    resp = await client.get("/api/cajas", headers=_h("sistema"))
    assert resp.status_code == 200, resp.text
    por_id = {c["id"]: c for c in resp.json()}
    assert {IDS["caja_a"], IDS["caja_b"]} <= set(por_id)
    assert por_id[IDS["caja_a"]]["sucursal_id"] == SUC_A
    assert por_id[IDS["caja_a"]]["sucursal_nombre"] == "Permisos Sucursal A"

    resp = await client.patch(
        f"/api/cajas/{IDS['caja_b']}",
        json={"nombre": "Permisos Caja B editada"},
        headers=_h("sistema"),
    )
    assert resp.status_code == 200, resp.text
    resp = await client.delete(f"/api/cajas/{IDS['caja_a']}", headers=_h("sistema"))
    assert resp.status_code == 204, resp.text
    filas = {
        str(r["id"]): r
        for r in await conn.fetch(
            "SELECT id, nombre, activo, sucursal_id FROM public.cajas WHERE id = ANY($1::uuid[])",
            [UUID(IDS["caja_a"]), UUID(IDS["caja_b"])],
        )
    }
    assert filas[IDS["caja_b"]]["nombre"] == "Permisos Caja B editada"
    assert str(filas[IDS["caja_b"]]["sucursal_id"]) == SUC_B
    assert filas[IDS["caja_a"]]["activo"] is False


async def test_admin_sigue_sin_editar_cajas_de_otra_sucursal(entorno: Any) -> None:
    client, conn = entorno
    resp = await client.patch(
        f"/api/cajas/{IDS['caja_b']}", json={"nombre": "Hackeada"}, headers=_h("admin_a")
    )
    assert resp.status_code == 404, resp.text
    resp = await client.get("/api/cajas", headers=_h("admin_a"))
    assert {c["sucursal_id"] for c in resp.json()} == {SUC_A}
    assert await conn.fetchval(
        "SELECT nombre FROM public.cajas WHERE id = $1", UUID(IDS["caja_b"])
    ) == ("Permisos Caja B")


# ── Historial de ventas del AdministradorSistema ───────────────────────────

_REPORTES_VENTAS = (
    "/api/pagos/historial",
    "/api/pagos/estadisticas",
    "/api/pagos/historial/export",
)


async def test_historial_de_ventas_pide_sucursal_al_sistema_sin_selector(entorno: Any) -> None:
    """Antes: 403 al AdministradorSistema en "Todas las sucursales". Ahora 422
    SUCURSAL_REQUERIDA, como el resto de reportes por sucursal."""
    client, _conn = entorno
    for ruta in _REPORTES_VENTAS:
        resp = await client.get(ruta, headers=_h("sistema"))
        assert resp.status_code == 422, (ruta, resp.text)
        assert resp.json()["detail"]["code"] == "SUCURSAL_REQUERIDA"


async def test_historial_de_ventas_con_sucursal_elegida_o_propia(entorno: Any) -> None:
    client, _conn = entorno
    for ruta in _REPORTES_VENTAS:
        for headers, query in (
            (_h("sistema", vista=SUC_A), ""),
            (_h("sistema"), f"?sucursal_id={SUC_B}"),
            (_h("admin_a"), ""),
            (_h("cajero_a"), f"?sucursal_id={SUC_A}"),
        ):
            resp = await client.get(f"{ruta}{query}", headers=headers)
            assert resp.status_code == 200, (ruta, query, resp.text)
        otra = await client.get(f"{ruta}?sucursal_id={SUC_B}", headers=_h("admin_a"))
        assert otra.status_code == 403, (ruta, otra.text)


# ── Catálogo de productos solo para quien vende o los gestiona ─────────────


@pytest.mark.parametrize(
    ("clave", "catalogo", "admin"),
    [
        ("atencion_a", 403, 403),
        ("inventario_a", 403, 403),
        ("cajero_a", 200, 403),
        ("admin_a", 200, 200),
    ],
)
async def test_lectura_del_catalogo_de_productos_por_rol(
    entorno: Any, clave: str, catalogo: int, admin: int
) -> None:
    client, _conn = entorno
    resp = await client.get("/api/productos/catalogo", headers=_h(clave))
    assert resp.status_code == catalogo, (clave, resp.text)
    resp = await client.get("/api/productos/admin", headers=_h(clave))
    assert resp.status_code == admin, (clave, resp.text)
