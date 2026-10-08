"""Contra PostgreSQL real, por HTTP: POST /api/pagos/completar
(y POST /api/comandas) cobran con el catálogo de la sucursal de la sesión.

Usa una BD desechable con sql/schema_maestro.sql cargado:

    TEST_DATABASE_URL=postgresql://dev:dev@localhost:PUERTO/woowkids \\
        pytest tests/db/test_precios_servidor_pos_pg.py

Se salta si TEST_DATABASE_URL no está definida. Cada prueba crea su propia
sucursal, cajero, caja, apertura y catálogo con ids nuevos, así que no
depende de datos previos ni choca con otras corridas.
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "postgresql://x/x"))
os.environ.setdefault("MINIO_ACCESS_KEY", "test-access-key")
os.environ.setdefault("MINIO_SECRET_KEY", "test-secret-key")

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL no definida")

CELULAR = "3312345678"


@dataclass
class Escenario:
    client: httpx.AsyncClient
    pool: asyncpg.Pool
    sucursal: UUID
    apertura: UUID
    efectivo: UUID
    tarjeta: UUID
    productos: dict[str, UUID]


async def _seed(conn: asyncpg.Connection) -> dict[str, Any]:
    sucursal, otra, cajero, caja = uuid4(), uuid4(), uuid4(), uuid4()
    for s in (sucursal, otra):
        await conn.execute(
            "INSERT INTO sucursales (id, nombre, clave) VALUES ($1, $2, $3)",
            s,
            f"Sucursal {s.hex[:6]}",
            s.hex[:8].upper(),
        )
    await conn.execute(
        "INSERT INTO usuarios (id, email, password_hash, nombre_completo, rol) "
        "VALUES ($1, $2, 'x', 'Cajera de prueba', 3)",
        cajero,
        f"cajera-{cajero.hex[:8]}@test.dev",
    )
    await conn.execute(
        "INSERT INTO usuarios_sucursal (usuario_id, sucursal_id) VALUES ($1, $2)", cajero, sucursal
    )
    await conn.execute(
        "INSERT INTO cajas (id, sucursal_id, codigo, nombre, numero) "
        "VALUES ($1, $2, $3, 'Caja', 1)",
        caja,
        sucursal,
        f"C{caja.hex[:6]}",
    )
    turno = await conn.fetchval("SELECT id FROM turnos ORDER BY nombre LIMIT 1")
    apertura = await conn.fetchval(
        "INSERT INTO apertura_caja (caja_id, cajero_id, turno_id, fondo_inicial, estado) "
        "VALUES ($1, $2, $3, 1000, 'ABIERTA') RETURNING id",
        caja,
        cajero,
        turno,
    )

    productos: dict[str, UUID] = {}

    async def producto(clave: str, nombre: str, precio: str, tipo: str, **extra: Any) -> None:
        pid = uuid4()
        productos[clave] = pid
        await conn.execute(
            "INSERT INTO productos "
            "(id, nombre, precio_unitario, tipo, sucursal_id, activo, es_combo) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            pid,
            f"{nombre} {pid.hex[:4]}",
            Decimal(precio),
            tipo,
            extra.get("sucursal", sucursal),
            extra.get("activo", True),
            extra.get("es_combo", False),
        )

    await producto("pizza", "Pizza individual", "95.00", "A")
    await producto("agua", "Agua embotellada", "22.00", "B")
    await producto("hotdog", "Hot dog", "70.00", "A")
    await producto("refresco", "Refresco", "30.00", "B")
    await producto("combo", "Combo Hot dog", "120.00", "C", es_combo=True)
    await producto("inactivo", "Taller de slime", "50.00", "A", activo=False)
    await producto("ajeno", "Pizza de otra sucursal", "10.00", "A", sucursal=otra)
    for hijo in ("hotdog", "refresco"):
        await conn.execute(
            "INSERT INTO producto_combo (combo_id, producto_id, cantidad) VALUES ($1, $2, 1)",
            productos["combo"],
            productos[hijo],
        )

    await conn.execute(
        "INSERT INTO configuracion_lealtad (sucursal_id, dias_caducidad, valor_punto, "
        "minimo_canje, otorga_puntos_comandas) VALUES ($1, 30, 1.00, 50, FALSE)",
        sucursal,
    )
    await conn.execute(
        "INSERT INTO lotes_puntos (sucursal_id, celular, puntos_otorgados, puntos_disponibles, "
        "fecha_caducidad) VALUES ($1, $2, 100, 100, NOW() + interval '30 days')",
        sucursal,
        CELULAR,
    )
    # En la sucursal de la prueba, la tarjeta exige referencia.
    await conn.execute("UPDATE metodos_pago SET requiere_referencia = TRUE WHERE tipo = 'T'")
    efectivo = await conn.fetchval("SELECT id FROM metodos_pago WHERE tipo = 'E'")
    tarjeta = await conn.fetchval("SELECT id FROM metodos_pago WHERE tipo = 'T'")
    return {
        "sucursal": sucursal,
        "cajero": cajero,
        "apertura": apertura,
        "efectivo": efectivo,
        "tarjeta": tarjeta,
        "productos": productos,
    }


@pytest_asyncio.fixture
async def escenario() -> AsyncIterator[Escenario]:
    from app.core.database import get_db
    from app.core.security import create_access_token
    from app.main import app
    from app.services import permission_service

    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=4)
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
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
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


def _renglon(producto_id: UUID, precio: str, cantidad: int = 1, **extra: Any) -> dict[str, Any]:
    return {
        "producto_id": str(producto_id),
        "nombre": "lo que diga el navegador",
        "cantidad": cantidad,
        "precio_unitario": precio,
        "subtotal": str(Decimal(precio) * cantidad),
        **extra,
    }


def _pago(metodo: UUID, monto: str, notas: str = "") -> dict[str, Any]:
    return {"metodo_pago_id": str(metodo), "monto": monto, "notas_pago": notas}


async def _cobrar(e: Escenario, detalles: list[Any], total: str, **extra: Any) -> httpx.Response:
    body = {
        "total_final": total,
        "detalles_comanda": detalles,
        "pagos": extra.pop("pagos", [_pago(e.efectivo, total)]),
        "nombre_cliente": "Cliente prueba",
        **extra,
    }
    return await e.client.post("/api/pagos/completar", json=body)


async def _sin_cobro(e: Escenario) -> None:
    async with e.pool.acquire() as conn:
        comandas = await conn.fetchval(
            "SELECT COUNT(*) FROM comandas WHERE sucursal_id = $1", e.sucursal
        )
        movimientos = await conn.fetchval(
            "SELECT COUNT(*) FROM movimientos_caja WHERE apertura_caja_id = $1", e.apertura
        )
    assert (comandas, movimientos) == (0, 0)


async def test_precio_manipulado_409_sin_cobrar(escenario: Escenario) -> None:
    e = escenario
    r = await _cobrar(e, [_renglon(e.productos["pizza"], "1.00")], "1.00")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "PRECIO_CAMBIADO"
    assert "cambió a $95.00. Actualiza el pedido." in detail["message"]
    await _sin_cobro(e)


async def test_precio_cambiado_en_el_catalogo_409(escenario: Escenario) -> None:
    e = escenario
    async with e.pool.acquire() as conn:
        await conn.execute(
            "UPDATE productos SET precio_unitario = 99 WHERE id = $1", e.productos["pizza"]
        )
    r = await _cobrar(e, [_renglon(e.productos["pizza"], "95.00")], "95.00")
    assert r.status_code == 409
    assert "cambió a $99.00" in r.json()["detail"]["message"]
    await _sin_cobro(e)


async def test_precio_correcto_201_con_precios_del_catalogo(escenario: Escenario) -> None:
    e = escenario
    r = await _cobrar(
        e,
        [_renglon(e.productos["pizza"], "95.00", 2), _renglon(e.productos["agua"], "22")],
        "212.00",
        pagos=[_pago(e.efectivo, "250.00")],
        cambio="38.00",
    )
    assert r.status_code == 201, r.text
    comanda_id = UUID(r.json()["id"])
    async with e.pool.acquire() as conn:
        total = await conn.fetchval("SELECT total_final FROM comandas WHERE id = $1", comanda_id)
        detalles = await conn.fetch(
            "SELECT producto_id, cantidad, precio_unitario, importe FROM detalles_comanda "
            "WHERE comanda_id = $1 ORDER BY importe DESC",
            comanda_id,
        )
        caja = await conn.fetch(
            "SELECT tipo_movimiento::text AS tipo, monto FROM movimientos_caja "
            "WHERE apertura_caja_id = $1 ORDER BY tipo_movimiento",
            e.apertura,
        )
    assert total == Decimal("212.00")
    assert [(d["cantidad"], d["precio_unitario"], d["importe"]) for d in detalles] == [
        (2, Decimal("95.00"), Decimal("190.00")),
        (1, Decimal("22.00"), Decimal("22.00")),
    ]
    assert sorted((m["tipo"], m["monto"]) for m in caja) == [
        ("C", Decimal("38.00")),
        ("O", Decimal("250.00")),
    ]


async def test_combo_con_hijos_validos_201_y_con_hijo_ajeno_422(escenario: Escenario) -> None:
    e = escenario
    p = e.productos

    def hijo(producto: UUID, instancia: str) -> dict[str, Any]:
        return _renglon(
            producto,
            "0",
            es_hijo_combo=True,
            es_hijo_de=str(p["combo"]),
            id_combo_padre=instancia,
        )

    i = str(uuid4())
    ajeno = await _cobrar(
        e,
        [
            _renglon(p["combo"], "120.00"),
            hijo(p["hotdog"], i),
            hijo(p["refresco"], i),
            hijo(p["pizza"], i),
        ],
        "120.00",
    )
    assert ajeno.status_code == 422, ajeno.text
    assert ajeno.json()["detail"]["code"] == "COMBO_INVALIDO"
    await _sin_cobro(e)

    ok = await _cobrar(
        e, [_renglon(p["combo"], "120.00"), hijo(p["hotdog"], i), hijo(p["refresco"], i)], "120.00"
    )
    assert ok.status_code == 201, ok.text
    async with e.pool.acquire() as conn:
        filas = await conn.fetch(
            "SELECT es_hijo_combo, precio_unitario, importe FROM detalles_comanda "
            "WHERE comanda_id = $1",
            UUID(ok.json()["id"]),
        )
    assert sorted((f["es_hijo_combo"], f["importe"]) for f in filas) == [
        (False, Decimal("120.00")),
        (True, Decimal("0.00")),
        (True, Decimal("0.00")),
    ]


async def test_cantidad_cero_422(escenario: Escenario) -> None:
    e = escenario
    r = await _cobrar(e, [_renglon(e.productos["pizza"], "95.00", 0)], "95.00")
    assert r.status_code == 422
    await _sin_cobro(e)


async def test_producto_inactivo_409_y_de_otra_sucursal_422(escenario: Escenario) -> None:
    e = escenario
    inactivo = await _cobrar(e, [_renglon(e.productos["inactivo"], "50.00")], "50.00")
    assert inactivo.status_code == 409
    assert inactivo.json()["detail"]["code"] == "PRODUCTO_NO_DISPONIBLE"
    ajeno = await _cobrar(e, [_renglon(e.productos["ajeno"], "10.00")], "10.00")
    assert ajeno.status_code == 422
    assert ajeno.json()["detail"]["code"] == "PRODUCTO_INVALIDO"
    await _sin_cobro(e)


async def test_tarjeta_sin_referencia_422_y_con_referencia_201(escenario: Escenario) -> None:
    e = escenario
    detalles = [_renglon(e.productos["agua"], "22.00")]
    sin = await _cobrar(e, detalles, "22.00", pagos=[_pago(e.tarjeta, "22.00")])
    assert sin.status_code == 422
    assert sin.json()["detail"]["code"] == "REFERENCIA_REQUERIDA"
    await _sin_cobro(e)
    con = await _cobrar(
        e, detalles, "22.00", pagos=[_pago(e.tarjeta, "22.00", "CREDITO - Folio: 778899")]
    )
    assert con.status_code == 201, con.text


async def test_descuento_por_puntos_sigue_funcionando(escenario: Escenario) -> None:
    e = escenario
    detalles = [_renglon(e.productos["pizza"], "95.00", 2)]
    # 190 - 60 puntos x $1 = 130. Si el cliente no descuenta, 409.
    malo = await _cobrar(e, detalles, "190.00", celular_cliente=CELULAR, puntos_a_redimir=60)
    assert malo.status_code == 409
    assert malo.json()["detail"]["code"] == "TOTAL_NO_COINCIDE"

    r = await _cobrar(e, detalles, "130.00", celular_cliente=CELULAR, puntos_a_redimir=60)
    assert r.status_code == 201, r.text
    async with e.pool.acquire() as conn:
        saldo = await conn.fetchval(
            "SELECT SUM(puntos_disponibles) FROM lotes_puntos "
            "WHERE sucursal_id = $1 AND celular = $2",
            e.sucursal,
            CELULAR,
        )
        total = await conn.fetchval(
            "SELECT total_final FROM comandas WHERE id = $1", UUID(r.json()["id"])
        )
    assert total == Decimal("130.00")
    assert saldo == 40


async def test_post_comandas_tambien_usa_el_catalogo(escenario: Escenario) -> None:
    e = escenario
    r = await e.client.post(
        "/api/comandas",
        json={
            "ticket_numero": "X1",
            "total_final": "1.00",
            "detalles_comanda": [_renglon(e.productos["pizza"], "1.00")],
        },
    )
    assert r.status_code == 409, r.text
    await _sin_cobro(e)
