"""M12 / M13 / M14 / M3 / B5 / N10 contra PostgreSQL real, por HTTP: datos del
ticket, hijos de combo enlazados a su renglón, servicios vendibles en caja,
cobros concurrentes con la misma Idempotency-Key, control optimista al editar
una orden y POST /comandas sin movimiento de caja.

Usa una BD desechable con sql/schema_maestro.sql cargado (TEST_DATABASE_URL);
se salta si no está definida. Cada prueba siembra su propia sucursal, cajero,
caja, apertura y catálogo con ids nuevos.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio

from tests.db.test_precios_servidor_pos_pg import Escenario, _pago, _renglon, _seed

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL no definida")

MIGRACION_093 = (
    Path(__file__).resolve().parents[2]
    / "sql"
    / "migrations"
    / "093_detalles_comanda_renglon_padre.sql"
)


@pytest_asyncio.fixture
async def esc() -> AsyncIterator[Escenario]:
    from app.core.database import get_db
    from app.core.security import create_access_token
    from app.main import app
    from app.services import permission_service

    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=12)
    async with pool.acquire() as conn:
        datos = await _seed(conn)
        await permission_service.load_cache(conn)

    async def get_db_prueba() -> AsyncIterator[asyncpg.Connection]:
        async with pool.acquire() as c:
            yield c

    app.dependency_overrides[get_db] = get_db_prueba
    token = create_access_token(
        {
            "sub": str(datos["cajero"]),
            "email": "cajera@test.dev",
            "role": "Cajero",
            "branch_id": str(datos["sucursal"]),
        },
        timedelta(minutes=10),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield Escenario(
            client=client,
            pool=pool,
            sucursal=datos["sucursal"],
            apertura=datos["apertura"],
            efectivo=datos["efectivo"],
            tarjeta=datos["tarjeta"],
            productos=datos["productos"],
        )
    app.dependency_overrides.pop(get_db, None)
    await pool.close()


def _body(detalles: list[Any], total: str, **extra: Any) -> dict[str, Any]:
    return {
        "total_final": total,
        "detalles_comanda": detalles,
        "pagos": extra.pop("pagos", None),
        "nombre_cliente": extra.pop("nombre_cliente", "Cliente prueba"),
        **extra,
    }


async def _cobrar(
    e: Escenario, detalles: list[Any], total: str, headers: dict[str, str] | None = None, **extra
) -> httpx.Response:
    body = _body(detalles, total, **extra)
    if body["pagos"] is None:
        body["pagos"] = [_pago(e.efectivo, total)]
    return await e.client.post("/api/pagos/completar", json=body, headers=headers)


def _hijo(e: Escenario, producto: str, instancia: str, notas: str | None = None) -> dict:
    return _renglon(
        e.productos[producto],
        "0",
        es_hijo_combo=True,
        es_hijo_de=str(e.productos["combo"]),
        id_combo_padre=instancia,
        notas_especiales=notas,
    )


def _combo(e: Escenario, cantidad: int = 1, notas: str | None = None) -> dict:
    return _renglon(e.productos["combo"], "120.00", cantidad, notas_especiales=notas)


async def _detalle(e: Escenario, comanda_id: str) -> dict[str, Any]:
    r = await e.client.get(f"/api/pagos/detalles/comanda/{comanda_id}")
    assert r.status_code == 200, r.text
    return r.json()


# ── M12: datos del ticket ────────────────────────────────────────────────────


async def test_ticket_trae_cliente_cambio_y_sucursal_de_la_venta(esc: Escenario) -> None:
    e = esc
    async with e.pool.acquire() as conn:
        await conn.execute(
            "UPDATE sucursales SET direccion = 'Av. Patria 1950', ciudad = 'Zapopan', "
            "estado = 'Jalisco', codigo_postal = '45160', telefono = '3333333333' WHERE id = $1",
            e.sucursal,
        )
    r = await _cobrar(
        e,
        [_renglon(e.productos["refresco"], "30.00")],
        "30.00",
        pagos=[_pago(e.efectivo, "50.00")],
        cambio="20.00",
        nombre_cliente="Mariana",
    )
    assert r.status_code == 201, r.text

    d = await _detalle(e, r.json()["id"])
    assert d["nombre_cliente"] == "Mariana"
    assert d["cambio"] == 20.0
    assert d["sucursal"]["direccion"] == "Av. Patria 1950"
    assert d["sucursal"]["ciudad"] == "Zapopan"
    assert d["sucursal"]["codigo_postal"] == "45160"
    assert d["sucursal"]["telefono"] == "3333333333"
    assert d["sucursal"]["nombre"].startswith("Sucursal ")


async def test_ticket_sin_cambio_trae_cero(esc: Escenario) -> None:
    e = esc
    r = await _cobrar(e, [_renglon(e.productos["agua"], "22.00")], "22.00")
    assert r.status_code == 201, r.text
    assert (await _detalle(e, r.json()["id"]))["cambio"] == 0.0


# ── M13: hijos de combo enlazados a su renglón ───────────────────────────────


async def test_combo_dividido_cada_hijo_apunta_a_su_renglon(esc: Escenario) -> None:
    e = esc
    i1, i2 = str(uuid4()), str(uuid4())
    r = await _cobrar(
        e,
        [
            _combo(e),
            _hijo(e, "hotdog", i1),
            _hijo(e, "refresco", i1),
            _combo(e, notas="segundo"),
            _hijo(e, "hotdog", i2),
            _hijo(e, "refresco", i2, notas="Sin hielo"),
        ],
        "240.00",
    )
    assert r.status_code == 201, r.text

    d = await _detalle(e, r.json()["id"])
    padres = [x for x in d["detalles"] if not x["nombre_combo_padre"]]
    hijos = [x for x in d["detalles"] if x["nombre_combo_padre"]]
    assert len(padres) == 2 and len(hijos) == 4
    por_padre: dict[str, list[dict]] = {}
    for h in hijos:
        por_padre.setdefault(h["detalle_padre_id"], []).append(h)
    assert set(por_padre) == {p["id"] for p in padres}
    segundo = next(p for p in padres if p["notas_especiales"] == "segundo")
    assert sorted(h["notas_especiales"] or "" for h in por_padre[segundo["id"]]) == [
        "",
        "Sin hielo",
    ]
    assert all(len(v) == 2 for v in por_padre.values())


async def test_dos_combos_en_un_renglon_comparten_padre(esc: Escenario) -> None:
    e = esc
    i1, i2 = str(uuid4()), str(uuid4())
    r = await _cobrar(
        e,
        [
            _combo(e, 2),
            _hijo(e, "hotdog", i1),
            _hijo(e, "refresco", i1),
            _hijo(e, "hotdog", i2),
            _hijo(e, "refresco", i2),
        ],
        "240.00",
    )
    assert r.status_code == 201, r.text
    d = await _detalle(e, r.json()["id"])
    padre = next(x for x in d["detalles"] if not x["nombre_combo_padre"])
    hijos = [x for x in d["detalles"] if x["nombre_combo_padre"]]
    assert len(hijos) == 4
    assert {h["detalle_padre_id"] for h in hijos} == {padre["id"]}


async def test_quitar_un_combo_quita_solo_sus_productos(esc: Escenario) -> None:
    e = esc
    i1, i2 = str(uuid4()), str(uuid4())
    r = await _cobrar(
        e,
        [
            _combo(e),
            _hijo(e, "hotdog", i1),
            _hijo(e, "refresco", i1),
            _combo(e, notas="quitar"),
            _hijo(e, "hotdog", i2),
            _hijo(e, "refresco", i2),
        ],
        "240.00",
    )
    assert r.status_code == 201, r.text
    comanda_id = r.json()["id"]
    d = await _detalle(e, comanda_id)
    quitar = next(x for x in d["detalles"] if x["notas_especiales"] == "quitar")

    # Solo el renglón del combo: el servidor quita también sus hijos.
    p = await e.client.patch(
        f"/api/comandas/{comanda_id}/detalles",
        json={"detalles_ids_a_eliminar": [quitar["id"]]},
    )
    assert p.status_code == 200, p.text
    d = await _detalle(e, comanda_id)
    assert len(d["detalles"]) == 3
    assert d["total_final"] == 120.0
    padre = next(x for x in d["detalles"] if not x["nombre_combo_padre"])
    assert {x["detalle_padre_id"] for x in d["detalles"] if x["nombre_combo_padre"]} == {
        padre["id"]
    }


async def test_cocina_separa_los_combos_por_unidad(esc: Escenario) -> None:
    e = esc
    i1, i2 = str(uuid4()), str(uuid4())
    r = await _cobrar(
        e,
        [
            _combo(e),
            _hijo(e, "hotdog", i1),
            _hijo(e, "refresco", i1),
            _combo(e),
            _hijo(e, "hotdog", i2),
            _hijo(e, "refresco", i2, notas="Sin hielo"),
        ],
        "240.00",
    )
    assert r.status_code == 201, r.text
    lista = await e.client.get("/api/comandas")
    assert lista.status_code == 200, lista.text
    comanda = next(c for c in lista.json() if c["id"] == r.json()["id"])
    # Cocina ve solo los productos (sin los renglones de combo), cuatro, en
    # dos unidades de combo con su nota donde va.
    instancias: dict[str, list[dict]] = {}
    for det in comanda["detalles"]:
        instancias.setdefault(det["id_combo_padre"], []).append(det)
    assert set(instancias) == {i1, i2}
    assert [d.get("notas_especiales") for d in instancias[i1]] == [None, None]
    assert sorted(d.get("notas_especiales") or "" for d in instancias[i2]) == ["", "Sin hielo"]


async def test_migracion_093_enlaza_filas_viejas_sin_ambiguedad(esc: Escenario) -> None:
    e = esc
    i1, i2, i3 = str(uuid4()), str(uuid4()), str(uuid4())
    unico = await _cobrar(
        e, [_combo(e, 1), _hijo(e, "hotdog", i1), _hijo(e, "refresco", i1)], "120.00"
    )
    doble = await _cobrar(
        e,
        [
            _combo(e),
            _hijo(e, "hotdog", i2),
            _hijo(e, "refresco", i2),
            _combo(e),
            _hijo(e, "hotdog", i3),
            _hijo(e, "refresco", i3),
        ],
        "240.00",
    )
    assert unico.status_code == 201 and doble.status_code == 201
    ids = [UUID(unico.json()["id"]), UUID(doble.json()["id"])]
    async with e.pool.acquire() as conn:
        # Como quedaban antes de la migración.
        await conn.execute(
            "UPDATE detalles_comanda SET detalle_padre_id = NULL WHERE comanda_id = ANY($1)", ids
        )
        await conn.execute(MIGRACION_093.read_text())
        await conn.execute(MIGRACION_093.read_text())  # idempotente
        filas = await conn.fetch(
            "SELECT comanda_id, detalle_padre_id FROM detalles_comanda "
            "WHERE comanda_id = ANY($1) AND es_hijo_combo",
            ids,
        )
        padre_unico = await conn.fetchval(
            "SELECT id FROM detalles_comanda WHERE comanda_id = $1 AND NOT es_hijo_combo", ids[0]
        )
    assert {f["detalle_padre_id"] for f in filas if f["comanda_id"] == ids[0]} == {padre_unico}
    # Dos renglones del mismo combo: ambiguo, se deja en NULL.
    assert {f["detalle_padre_id"] for f in filas if f["comanda_id"] == ids[1]} == {None}


# ── M14: servicios ───────────────────────────────────────────────────────────


async def test_servicio_aparece_en_catalogo_y_se_vende_sin_inventario(esc: Escenario) -> None:
    e = esc
    servicio = uuid4()
    async with e.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO productos (id, nombre, precio_unitario, tipo, sucursal_id) "
            "VALUES ($1, 'Pintacaritas', 60, 'S', $2)",
            servicio,
            e.sucursal,
        )
    catalogo = await e.client.get("/api/productos/catalogo")
    assert catalogo.status_code == 200, catalogo.text
    fila = next(p for p in catalogo.json() if p["id"] == str(servicio))
    assert fila["tipo"] == "S" and fila["disponible_estimado"] is None

    r = await _cobrar(e, [_renglon(servicio, "60.00", 2)], "120.00")
    assert r.status_code == 201, r.text
    async with e.pool.acquire() as conn:
        movimientos = await conn.fetchval(
            "SELECT COUNT(*) FROM movimientos_inventario WHERE referencia_id = $1",
            UUID(r.json()["id"]),
        )
    assert movimientos == 0


async def test_combo_trae_disponible_estimado_de_sus_integrantes(esc: Escenario) -> None:
    e = esc
    async with e.pool.acquire() as conn:
        pza = await conn.fetchval("SELECT id FROM unidades_medida WHERE codigo = 'pza'")
        insumos = {}
        for clave, stock in (("pan", 10), ("lata", 3)):
            insumos[clave] = await conn.fetchval(
                "INSERT INTO insumos (sucursal_id, nombre, unidad_base_id, unidad_compra_id, "
                "stock_actual) VALUES ($1, $2, $3, $3, $4) RETURNING id",
                e.sucursal,
                f"{clave} {uuid4().hex[:6]}",
                pza,
                stock,
            )
        for producto, insumo in (("hotdog", "pan"), ("refresco", "lata")):
            await conn.execute(
                "INSERT INTO producto_insumos (producto_id, insumo_id, cantidad) "
                "VALUES ($1, $2, 1)",
                e.productos[producto],
                insumos[insumo],
            )
    catalogo = await e.client.get("/api/productos/catalogo")
    assert catalogo.status_code == 200, catalogo.text
    por_id = {p["id"]: p for p in catalogo.json()}
    assert por_id[str(e.productos["combo"])]["disponible_estimado"] == 3
    assert por_id[str(e.productos["hotdog"])]["disponible_estimado"] == 10


# ── M3: cobros concurrentes con la misma Idempotency-Key ─────────────────────


async def test_cobros_concurrentes_misma_clave_devuelven_la_misma_venta(esc: Escenario) -> None:
    e = esc
    clave = f"pos-{uuid4()}"
    detalles = [_renglon(e.productos["pizza"], "95.00")]
    respuestas = await asyncio.gather(
        *(_cobrar(e, detalles, "95.00", headers={"Idempotency-Key": clave}) for _ in range(5))
    )
    assert [r.status_code for r in respuestas] == [201] * 5, [r.text for r in respuestas]
    assert len({r.json()["id"] for r in respuestas}) == 1
    async with e.pool.acquire() as conn:
        comandas = await conn.fetchval(
            "SELECT COUNT(*) FROM comandas WHERE sucursal_id = $1", e.sucursal
        )
        pagos = await conn.fetchval(
            "SELECT COUNT(*) FROM pagos_ordenes WHERE sucursal_id = $1", e.sucursal
        )
        caja = await conn.fetchval(
            "SELECT COUNT(*) FROM movimientos_caja WHERE apertura_caja_id = $1", e.apertura
        )
    assert (comandas, pagos, caja) == (1, 1, 1)


# ── B5: control optimista al editar una orden ────────────────────────────────


async def test_editar_orden_con_version_vieja_409(esc: Escenario) -> None:
    e = esc
    r = await _cobrar(
        e,
        [_renglon(e.productos["pizza"], "95.00"), _renglon(e.productos["agua"], "22.00")],
        "117.00",
    )
    assert r.status_code == 201, r.text
    comanda_id = r.json()["id"]
    d = await _detalle(e, comanda_id)
    version = d["modificado"]
    assert version
    pizza, agua = sorted(d["detalles"], key=lambda x: -x["importe"])

    # Otra pestaña quita la pizza con la versión que leyó.
    otra = await e.client.patch(
        f"/api/comandas/{comanda_id}/detalles",
        json={"detalles_ids_a_eliminar": [pizza["id"]], "modificado_esperado": version},
    )
    assert otra.status_code == 200, otra.text

    # Esta pestaña sigue con la versión vieja: 409 y no toca nada.
    vieja = await e.client.patch(
        f"/api/comandas/{comanda_id}/detalles",
        json={"detalles_ids_a_eliminar": [agua["id"]], "modificado_esperado": version},
    )
    assert vieja.status_code == 409, vieja.text
    assert vieja.json()["detail"]["code"] == "COMANDA_MODIFICADA"
    d2 = await _detalle(e, comanda_id)
    assert [x["id"] for x in d2["detalles"]] == [agua["id"]]

    # Con la versión nueva sí se aplica (aquí: quitar lo último cancela; se
    # prueba con la cancelación de cobradas → 409 de A4, no de versión).
    nueva = await e.client.patch(
        f"/api/comandas/{comanda_id}/detalles",
        json={"detalles_ids_a_eliminar": [agua["id"]], "modificado_esperado": d2["modificado"]},
    )
    assert nueva.status_code == 409
    assert nueva.json()["detail"]["code"] == "COMANDA_PAGADA_USAR_CANCELAR"


async def test_editar_orden_sin_version_sigue_funcionando(esc: Escenario) -> None:
    e = esc
    r = await _cobrar(
        e,
        [_renglon(e.productos["pizza"], "95.00"), _renglon(e.productos["agua"], "22.00")],
        "117.00",
    )
    comanda_id = r.json()["id"]
    d = await _detalle(e, comanda_id)
    agua = next(x for x in d["detalles"] if x["importe"] == 22.0)
    p = await e.client.patch(
        f"/api/comandas/{comanda_id}/detalles", json={"detalles_ids_a_eliminar": [agua["id"]]}
    )
    assert p.status_code == 200, p.text


# ── N10: POST /comandas sin movimiento de caja ───────────────────────────────


async def test_post_comandas_no_registra_venta_en_caja(esc: Escenario) -> None:
    e = esc
    r = await e.client.post(
        "/api/comandas",
        json={
            "ticket_numero": "X1",
            "total_final": "95.00",
            "detalles_comanda": [_renglon(e.productos["pizza"], "95.00")],
        },
    )
    assert r.status_code == 201, r.text
    async with e.pool.acquire() as conn:
        movimientos = await conn.fetchval(
            "SELECT COUNT(*) FROM movimientos_caja WHERE apertura_caja_id = $1", e.apertura
        )
    assert movimientos == 0
    assert Decimal(str(r.json()["total_final"])) == Decimal("95.00")
