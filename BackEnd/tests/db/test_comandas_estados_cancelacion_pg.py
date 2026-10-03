"""A2 / M27 / A4 contra PostgreSQL real, por HTTP: máquina de estados de las
comandas, cancelación sin "zombies" ni doble reversión de stock, una sola
emisión WebSocket por cambio, y la cancelación de comandas cobradas con PIN de
administrador y devolución en el arqueo.

Usa una BD desechable con sql/schema_maestro.sql cargado (TEST_DATABASE_URL);
se salta si no está definida. Cada prueba siembra su propia sucursal, usuarios,
caja, apertura y catálogo con ids nuevos.
"""

from __future__ import annotations

import asyncio
import os
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

PIN_ADMIN = "4321"


@dataclass
class Esc:
    pool: asyncpg.Pool
    cajero: httpx.AsyncClient
    cocina: httpx.AsyncClient
    sucursal: UUID
    cajero_id: UUID
    apertura: UUID
    caja: UUID
    admin_email: str
    admin_otra_email: str
    efectivo: UUID
    tarjeta: UUID
    hotdog: UUID
    insumo: UUID


async def _seed(conn: asyncpg.Connection) -> dict[str, Any]:
    from app.core.security import hash_password

    sucursal, otra = uuid4(), uuid4()
    for s in (sucursal, otra):
        await conn.execute(
            "INSERT INTO sucursales (id, nombre, clave) VALUES ($1, $2, $3)",
            s,
            f"Sucursal {s.hex[:6]}",
            s.hex[:8].upper(),
        )

    async def usuario(rol: int, suc: UUID, pin: str | None = None) -> tuple[UUID, str]:
        uid = uuid4()
        email = f"u-{uid.hex[:10]}@test.dev"
        await conn.execute(
            "INSERT INTO usuarios (id, email, password_hash, nombre_completo, rol, pin_hash) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            uid,
            email,
            hash_password("otra-cosa"),
            f"Usuario {uid.hex[:6]}",
            rol,
            hash_password(pin) if pin else None,
        )
        await conn.execute(
            "INSERT INTO usuarios_sucursal (usuario_id, sucursal_id) VALUES ($1, $2)", uid, suc
        )
        return uid, email

    cajero, _ = await usuario(3, sucursal)
    cocina, _ = await usuario(4, sucursal)
    _, admin_email = await usuario(2, sucursal, PIN_ADMIN)
    _, admin_otra_email = await usuario(2, otra, PIN_ADMIN)

    caja = uuid4()
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

    hotdog = uuid4()
    await conn.execute(
        "INSERT INTO productos (id, nombre, precio_unitario, tipo, sucursal_id, activo, es_combo) "
        "VALUES ($1, $2, 70.00, 'A', $3, TRUE, FALSE)",
        hotdog,
        f"Hot dog {hotdog.hex[:4]}",
        sucursal,
    )
    pza = await conn.fetchval("SELECT id FROM unidades_medida WHERE codigo = 'pza'")
    insumo = await conn.fetchval(
        "INSERT INTO insumos (sucursal_id, nombre, unidad_base_id, unidad_compra_id, "
        "stock_actual) VALUES ($1, $2, $3, $3, 10) RETURNING id",
        sucursal,
        f"Pan {hotdog.hex[:4]}",
        pza,
    )
    await conn.execute(
        "INSERT INTO producto_insumos (producto_id, insumo_id, cantidad) VALUES ($1, $2, 1)",
        hotdog,
        insumo,
    )
    return {
        "sucursal": sucursal,
        "cajero": cajero,
        "cocina": cocina,
        "apertura": apertura,
        "caja": caja,
        "admin_email": admin_email,
        "admin_otra_email": admin_otra_email,
        "efectivo": await conn.fetchval("SELECT id FROM metodos_pago WHERE tipo = 'E'"),
        "tarjeta": await conn.fetchval("SELECT id FROM metodos_pago WHERE tipo = 'T'"),
        "hotdog": hotdog,
        "insumo": insumo,
    }


def _usuario(sub: UUID, sucursal: UUID) -> Any:
    from datetime import UTC, datetime

    from app.schemas.auth import TokenData

    return TokenData(
        sub=str(sub),
        email="c@test.dev",
        role="Cajero",
        branch_id=sucursal,
        jti=uuid4().hex,
        exp=datetime.now(UTC) + timedelta(minutes=10),
    )


def _token(sub: UUID, role: str, sucursal: UUID) -> str:
    from app.core.security import create_access_token

    return create_access_token(
        {"sub": str(sub), "email": f"{role}@test.dev", "role": role, "branch_id": str(sucursal)},
        timedelta(minutes=10),
    )


@pytest_asyncio.fixture
async def esc() -> AsyncIterator[Esc]:
    from app.core.database import get_db
    from app.main import app
    from app.services import permission_service

    pool = await asyncpg.create_pool(TEST_DATABASE_URL, min_size=1, max_size=12)
    async with pool.acquire() as conn:
        d = await _seed(conn)
        await permission_service.load_cache(conn)

    async def get_db_prueba() -> AsyncIterator[asyncpg.Connection]:
        async with pool.acquire() as c:
            yield c

    app.dependency_overrides[get_db] = get_db_prueba
    transport = httpx.ASGITransport(app=app)

    def cliente(sub: UUID, role: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {_token(sub, role, d['sucursal'])}"},
        )

    async with cliente(d["cajero"], "Cajero") as cajero, cliente(d["cocina"], "Cocina") as cocina:
        yield Esc(
            pool=pool,
            cajero=cajero,
            cocina=cocina,
            sucursal=d["sucursal"],
            cajero_id=d["cajero"],
            apertura=d["apertura"],
            caja=d["caja"],
            admin_email=d["admin_email"],
            admin_otra_email=d["admin_otra_email"],
            efectivo=d["efectivo"],
            tarjeta=d["tarjeta"],
            hotdog=d["hotdog"],
            insumo=d["insumo"],
        )
    app.dependency_overrides.pop(get_db, None)
    await pool.close()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _renglon(e: Esc, cantidad: int = 1) -> dict[str, Any]:
    return {
        "producto_id": str(e.hotdog),
        "nombre": "Hot dog",
        "cantidad": cantidad,
        "precio_unitario": "70.00",
        "subtotal": str(Decimal("70.00") * cantidad),
    }


async def _cobrada(
    e: Esc, cantidad: int = 1, pagos: list[dict[str, Any]] | None = None, cambio: str = "0"
) -> str:
    """Comanda del POS cobrada (POST /api/pagos/completar)."""
    total = str(Decimal("70.00") * cantidad)
    body = {
        "total_final": total,
        "detalles_comanda": [_renglon(e, cantidad)],
        "pagos": pagos or [{"metodo_pago_id": str(e.efectivo), "monto": total, "notas_pago": ""}],
        "cambio": cambio,
        "nombre_cliente": "Cliente prueba",
    }
    r = await e.cajero.post("/api/pagos/completar", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _sin_cobro(e: Esc, cantidad: int = 1) -> str:
    """Comanda sin pagos ni movimiento de caja (como las automáticas de eventos)."""
    from app.schemas.comanda import ComandaCreate, DetalleCreate
    from app.services import comanda_service

    comanda_in = ComandaCreate(
        ticket_numero=f"E{uuid4().hex[:6]}",
        total_final=Decimal("70.00") * cantidad,
        detalles_comanda=[DetalleCreate(**_renglon(e, cantidad))],
        sucursal_id=e.sucursal,
    )
    user = _usuario(e.cajero_id, e.sucursal)
    async with e.pool.acquire() as conn:
        comanda = await comanda_service.crear_comanda(conn, comanda_in, user, None)
    return comanda.id


async def _patch(
    cliente: httpx.AsyncClient, comanda_id: str, estado: str, **extra: Any
) -> httpx.Response:
    return await cliente.patch(
        f"/api/comandas/{comanda_id}/estado", json={"estado_actual": estado, **extra}
    )


async def _cancelar(cliente: httpx.AsyncClient, comanda_id: str, **extra: Any) -> httpx.Response:
    motivo = "Cliente se arrepintió"
    return await _patch(cliente, comanda_id, "C", motivo_cancelacion=motivo, **extra)


async def _token_admin(e: Esc, email: str | None = None, turno: UUID | None = None) -> str:
    r = await e.cajero.post(
        "/api/turnos-caja/validar-pin-admin",
        json={
            "turno_id": str(turno or e.apertura),
            "admin_email": email or e.admin_email,
            "pin": PIN_ADMIN,
        },
    )
    assert r.status_code == 200, r.text
    return str(r.json()["token_pin"])


async def _comanda(e: Esc, comanda_id: str) -> asyncpg.Record:
    async with e.pool.acquire() as conn:
        return await conn.fetchrow(
            "SELECT estado_actual, activo FROM comandas WHERE id = $1", UUID(comanda_id)
        )


async def _stock(e: Esc) -> Decimal:
    async with e.pool.acquire() as conn:
        return Decimal(
            await conn.fetchval("SELECT stock_actual FROM insumos WHERE id = $1", e.insumo)
        )


async def _reversiones(e: Esc, comanda_id: str) -> int:
    async with e.pool.acquire() as conn:
        return int(
            await conn.fetchval(
                "SELECT COUNT(*) FROM movimientos_inventario "
                "WHERE referencia_id = $1 AND motivo = 'cancelacion_comanda'",
                UUID(comanda_id),
            )
        )


async def _efectivo_esperado(e: Esc, apertura: UUID | None = None) -> tuple[Decimal, Decimal]:
    """(efectivo disponible en vivo, efectivo esperado del arqueo)."""
    from app.repositories.caja_repository import get_apertura_por_id
    from app.services import turnos_caja_service

    apertura_id = str(apertura or e.apertura)
    async with e.pool.acquire() as conn:
        disponible = await turnos_caja_service.efectivo_disponible_actual(conn, apertura_id)
        fila = await get_apertura_por_id(conn, apertura_id)
        assert fila is not None
        _, _, _, balance = await turnos_caja_service._calcular_balance(conn, fila, apertura_id)
    return disponible, balance[0].esperado


async def _devoluciones(e: Esc, comanda_id: str) -> list[asyncpg.Record]:
    async with e.pool.acquire() as conn:
        return await conn.fetch(
            "SELECT apertura_caja_id, es_efectivo, monto, metodo_pago_id "
            "FROM devoluciones_comanda WHERE comanda_id = $1 ORDER BY es_efectivo DESC",
            UUID(comanda_id),
        )


# ── A2: máquina de estados ───────────────────────────────────────────────────


async def test_estados_solo_avanzan_un_paso(esc: Esc) -> None:
    cid = await _sin_cobro(esc)

    for invalido in ("T", "L", "P"):
        r = await _patch(esc.cocina, cid, invalido)
        assert r.status_code == 409, (invalido, r.text)
        assert r.json()["detail"]["code"] == "TRANSICION_COMANDA_INVALIDA"

    assert (await _patch(esc.cocina, cid, "E")).status_code == 200
    r = await _patch(esc.cocina, cid, "P")  # retroceder
    assert r.status_code == 409
    assert (await _patch(esc.cocina, cid, "L")).status_code == 200
    assert (await _patch(esc.cocina, cid, "T")).status_code == 200

    for despues in ("E", "L", "T", "C"):
        r = await _patch(esc.cocina, cid, despues, motivo_cancelacion="x")
        assert r.status_code == 409, (despues, r.text)
    assert tuple(await _comanda(esc, cid)) == ("T", True)


@pytest.mark.parametrize("valor", ["X", "", "c", "TT"])
async def test_estado_invalido_422(esc: Esc, valor: str) -> None:
    cid = await _sin_cobro(esc)
    r = await _patch(esc.cocina, cid, valor)
    assert r.status_code == 422, r.text
    assert tuple(await _comanda(esc, cid)) == ("P", True)


async def test_check_en_bd_rechaza_estado_invalido(esc: Esc) -> None:
    cid = await _sin_cobro(esc)
    async with esc.pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("UPDATE comandas SET estado_actual = 'X' WHERE id = $1", UUID(cid))


async def test_cancelada_no_vuelve_a_cocina(esc: Esc) -> None:
    """El "zombie": una cancelada (activo=false) volvía al tablero al
    cambiarle el estado."""
    cid = await _sin_cobro(esc)
    assert (await _cancelar(esc.cocina, cid)).status_code == 200

    r = await _patch(esc.cocina, cid, "E")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "COMANDA_CANCELADA"
    assert tuple(await _comanda(esc, cid)) == ("C", False)

    # Y una inactiva que quedó en un estado de cocina (datos viejos) no se lista.
    zombie = await _sin_cobro(esc)
    async with esc.pool.acquire() as conn:
        await conn.execute(
            "UPDATE comandas SET estado_actual = 'E', activo = FALSE WHERE id = $1", UUID(zombie)
        )
    r = await esc.cocina.get("/api/comandas")
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()}
    assert cid not in ids and zombie not in ids
    assert (await _patch(esc.cocina, zombie, "L")).status_code == 409


async def test_ciclo_c_t_c_revierte_stock_una_sola_vez(esc: Esc) -> None:
    cid = await _sin_cobro(esc, cantidad=2)
    assert await _stock(esc) == Decimal("8")

    assert (await _cancelar(esc.cocina, cid)).status_code == 200
    assert await _stock(esc) == Decimal("10")

    assert (await _patch(esc.cocina, cid, "T")).status_code == 409
    assert (await _cancelar(esc.cocina, cid)).status_code == 409
    assert await _stock(esc) == Decimal("10")
    assert await _reversiones(esc, cid) == 1


async def test_cancelaciones_simultaneas_revierten_una_vez(esc: Esc) -> None:
    from app.exceptions.comandas import ComandaCanceladaError
    from app.services import comanda_service

    cid = await _sin_cobro(esc, cantidad=3)
    user = _usuario(esc.cajero_id, esc.sucursal)

    async def cancelar() -> Any:
        async with esc.pool.acquire() as conn:
            return await comanda_service.cambiar_estado(
                conn, cid, "C", user, motivo_cancelacion="duplicado"
            )

    resultados = await asyncio.gather(*(cancelar() for _ in range(6)), return_exceptions=True)
    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    assert len(exitos) == 1
    assert all(isinstance(r, ComandaCanceladaError) for r in resultados if r not in exitos)
    assert await _stock(esc) == Decimal("10")
    assert await _reversiones(esc, cid) == 1
