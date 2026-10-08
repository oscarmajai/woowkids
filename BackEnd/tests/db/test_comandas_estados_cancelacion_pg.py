"""Contra PostgreSQL real, por HTTP: máquina de estados de las
comandas, cancelación sin "zombies" ni doble reversión de stock, una sola
emisión WebSocket por cambio, la cancelación de comandas cobradas con PIN de
administrador y devolución en el arqueo (de cada método, no solo el
efectivo), y la devolución de comandas ya entregadas sin regresar stock.

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
from unittest.mock import AsyncMock
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
    cajero_email: str
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

    # Con PIN, para probar que un cajero no autoriza aunque lo conozca.
    cajero, cajero_email = await usuario(3, sucursal, PIN_ADMIN)
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
        "cajero_email": cajero_email,
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
            cajero_email=d["cajero_email"],
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


# ── Máquina de estados ───────────────────────────────────────────────────────


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


# ── Una sola emisión por cambio ──────────────────────────────────────────────


async def test_un_solo_broadcast_por_cambio_de_estado(
    esc: Esc, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.ws_manager import manager

    cid = await _sin_cobro(esc)
    emitir = AsyncMock()
    monkeypatch.setattr(manager, "broadcast", emitir)

    assert (await _patch(esc.cocina, cid, "E")).status_code == 200
    assert emitir.await_count == 1
    sucursal, mensaje = emitir.await_args.args
    assert sucursal == str(esc.sucursal)
    assert mensaje["type"] == "comanda_actualizada"
    assert mensaje["comanda"]["estado_actual"] == "E"


# ── Cancelar una comanda cobrada ─────────────────────────────────────────────


async def test_cancelar_pagada_sin_pin_403_y_no_cancela(esc: Esc) -> None:
    cid = await _cobrada(esc)
    r = await _cancelar(esc.cajero, cid)
    assert r.status_code == 403, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "AUTORIZACION_ADMIN_REQUERIDA"
    assert detail["turno_id"] == str(esc.apertura)
    assert tuple(await _comanda(esc, cid)) == ("P", True)
    assert await _devoluciones(esc, cid) == []


async def test_cancelar_pagada_en_efectivo_resta_del_arqueo(esc: Esc) -> None:
    # Paga $100 por $70 y recibe $30 de cambio: al cajón entraron $70.
    cid = await _cobrada(
        esc,
        pagos=[{"metodo_pago_id": str(esc.efectivo), "monto": "100.00", "notas_pago": ""}],
        cambio="30.00",
    )
    assert await _efectivo_esperado(esc) == (Decimal("1070.00"), Decimal("1070.00"))
    assert await _stock(esc) == Decimal("9")

    token = await _token_admin(esc)
    r = await _cancelar(esc.cajero, cid, token_pin_admin=token)
    assert r.status_code == 200, r.text

    assert tuple(await _comanda(esc, cid)) == ("C", False)
    assert await _stock(esc) == Decimal("10")
    devs = await _devoluciones(esc, cid)
    assert [(d["es_efectivo"], d["monto"]) for d in devs] == [(True, Decimal("70.00"))]
    assert devs[0]["apertura_caja_id"] == esc.apertura
    assert await _efectivo_esperado(esc) == (Decimal("1000.00"), Decimal("1000.00"))

    # El token es de un solo uso.
    otra = await _cobrada(esc)
    r = await _cancelar(esc.cajero, otra, token_pin_admin=token)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "PIN_TOKEN_REQUERIDO"
    assert tuple(await _comanda(esc, otra)) == ("P", True)


async def test_devolucion_no_puede_exceder_el_efectivo_del_cajon(esc: Esc) -> None:
    cid = await _cobrada(esc)
    r = await esc.cajero.post(
        "/api/turnos-caja/retiro",
        json={
            "apertura_caja_id": str(esc.apertura),
            "tipo_destinatario": "Empleado",
            "monto": "1050.00",
        },
    )
    assert r.status_code == 201, r.text

    r = await _cancelar(esc.cajero, cid, token_pin_admin=await _token_admin(esc))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "EFECTIVO_INSUFICIENTE"
    assert tuple(await _comanda(esc, cid)) == ("P", True)
    assert await _devoluciones(esc, cid) == []


async def test_cancelar_pagada_con_tarjeta_no_mueve_el_efectivo(esc: Esc) -> None:
    cid = await _cobrada(
        esc,
        pagos=[
            {"metodo_pago_id": str(esc.tarjeta), "monto": "70.00", "notas_pago": "Folio: 98765"}
        ],
    )
    antes = await _efectivo_esperado(esc)

    r = await _cancelar(esc.cajero, cid, token_pin_admin=await _token_admin(esc))
    assert r.status_code == 200, r.text

    devs = await _devoluciones(esc, cid)
    assert [(d["es_efectivo"], d["monto"], d["metodo_pago_id"]) for d in devs] == [
        (False, Decimal("70.00"), esc.tarjeta)
    ]
    assert await _efectivo_esperado(esc) == antes


async def test_admin_de_otra_sucursal_no_autoriza(esc: Esc) -> None:
    # El admin de otra sucursal no obtiene token: validar-pin-admin
    # lo rechaza antes de probar el PIN. La revisión al consumir el token
    # (ADMIN_NO_AUTORIZADO) queda como defensa en profundidad.
    cid = await _cobrada(esc)
    r = await esc.cajero.post(
        "/api/turnos-caja/validar-pin-admin",
        json={
            "turno_id": str(esc.apertura),
            "admin_email": esc.admin_otra_email,
            "pin": PIN_ADMIN,
        },
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "AUTORIZADOR_NO_VALIDO"
    r = await _cancelar(esc.cajero, cid, token_pin_admin="token-inexistente")
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "PIN_TOKEN_REQUERIDO"
    assert tuple(await _comanda(esc, cid)) == ("P", True)
    assert await _devoluciones(esc, cid) == []


async def test_cancelar_pagada_sin_turno_abierto_409(esc: Esc) -> None:
    cid = await _cobrada(esc)
    r = await _cancelar(esc.cocina, cid, token_pin_admin="cualquiera")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "TURNO_NO_ABIERTO"
    assert tuple(await _comanda(esc, cid)) == ("P", True)


async def test_venta_de_turno_cerrado_409(esc: Esc) -> None:
    cid = await _cobrada(esc)
    async with esc.pool.acquire() as conn:
        await conn.execute(
            "UPDATE apertura_caja SET estado = 'CERRADA' WHERE id = $1", esc.apertura
        )
        nueva = await conn.fetchval(
            "INSERT INTO apertura_caja (caja_id, cajero_id, turno_id, fondo_inicial, estado) "
            "SELECT caja_id, cajero_id, turno_id, 500, 'ABIERTA' FROM apertura_caja "
            "WHERE id = $1 RETURNING id",
            esc.apertura,
        )
    r = await _cancelar(esc.cajero, cid, token_pin_admin=await _token_admin(esc, turno=nueva))
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "VENTA_DE_TURNO_CERRADO"
    assert tuple(await _comanda(esc, cid)) == ("P", True)


async def test_quitar_todos_los_productos_de_una_pagada_409(esc: Esc) -> None:
    cid = await _cobrada(esc)
    async with esc.pool.acquire() as conn:
        ids = [
            str(r["id"])
            for r in await conn.fetch(
                "SELECT id FROM detalles_comanda WHERE comanda_id = $1", UUID(cid)
            )
        ]
    r = await esc.cajero.patch(
        f"/api/comandas/{cid}/detalles",
        json={"detalles_ids_a_eliminar": ids, "motivo_cancelacion": "Otro"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "COMANDA_PAGADA_USAR_CANCELAR"
    assert tuple(await _comanda(esc, cid)) == ("P", True)


async def test_cancelar_sin_pagos_no_pide_pin(esc: Esc) -> None:
    cid = await _sin_cobro(esc)
    r = await _cancelar(esc.cocina, cid)
    assert r.status_code == 200, r.text
    assert await _devoluciones(esc, cid) == []


# ── Cada devolución baja el esperado de SU método ────────────────────────────


async def _balance(e: Esc) -> tuple[Decimal, dict[str, Any]]:
    """(total esperado general, renglones del arqueo por método)."""
    from app.repositories.caja_repository import get_apertura_por_id
    from app.services import turnos_caja_service

    async with e.pool.acquire() as conn:
        fila = await get_apertura_por_id(conn, str(e.apertura))
        assert fila is not None
        total, _, _, balance = await turnos_caja_service._calcular_balance(
            conn, fila, str(e.apertura)
        )
    return total, {b.metodo: b for b in balance}


async def _nombre_tarjeta(e: Esc) -> str:
    async with e.pool.acquire() as conn:
        return str(
            await conn.fetchval("SELECT lower(nombre) FROM metodos_pago WHERE id = $1", e.tarjeta)
        )


async def test_cancelar_pagada_con_tarjeta_baja_el_esperado_de_tarjeta(esc: Esc) -> None:
    cid = await _cobrada(
        esc,
        pagos=[{"metodo_pago_id": str(esc.tarjeta), "monto": "70.00", "notas_pago": "Folio: 1"}],
    )
    tarjeta = await _nombre_tarjeta(esc)
    total_antes, filas = await _balance(esc)
    assert filas[tarjeta].esperado == Decimal("70.00")
    assert filas[tarjeta].devoluciones == Decimal("0")

    r = await _cancelar(esc.cajero, cid, token_pin_admin=await _token_admin(esc))
    assert r.status_code == 200, r.text

    total, filas = await _balance(esc)
    # Antes quedaba esperado 70 en tarjeta: una diferencia falsa en el arqueo.
    assert filas[tarjeta].esperado == Decimal("0.00")
    assert filas[tarjeta].devoluciones == Decimal("70.00")
    assert filas["efectivo"].esperado == Decimal("1000.00")
    assert filas["efectivo"].devoluciones == Decimal("0")
    assert total == total_antes - Decimal("70.00")


async def test_cancelar_pago_mixto_baja_cada_metodo(esc: Esc) -> None:
    cid = await _cobrada(
        esc,
        pagos=[
            {"metodo_pago_id": str(esc.efectivo), "monto": "40.00", "notas_pago": ""},
            {"metodo_pago_id": str(esc.tarjeta), "monto": "30.00", "notas_pago": "Folio: 2"},
        ],
    )
    tarjeta = await _nombre_tarjeta(esc)
    total_antes, filas = await _balance(esc)
    assert filas["efectivo"].esperado == Decimal("1040.00")
    assert filas[tarjeta].esperado == Decimal("30.00")

    r = await _cancelar(esc.cajero, cid, token_pin_admin=await _token_admin(esc))
    assert r.status_code == 200, r.text

    devs = await _devoluciones(esc, cid)
    assert [(d["es_efectivo"], d["monto"]) for d in devs] == [
        (True, Decimal("40.00")),
        (False, Decimal("30.00")),
    ]
    total, filas = await _balance(esc)
    assert (filas["efectivo"].esperado, filas["efectivo"].devoluciones) == (
        Decimal("1000.00"),
        Decimal("40.00"),
    )
    assert (filas[tarjeta].esperado, filas[tarjeta].devoluciones) == (
        Decimal("0.00"),
        Decimal("30.00"),
    )
    assert total == total_antes - Decimal("70.00")
    assert await _efectivo_esperado(esc) == (Decimal("1000.00"), Decimal("1000.00"))


# ── Devolución de una comanda ya entregada ───────────────────────────────────


async def _entregar(e: Esc, comanda_id: str) -> None:
    for estado in ("E", "L", "T"):
        r = await _patch(e.cocina, comanda_id, estado)
        assert r.status_code == 200, r.text


async def _devolver(
    cliente: httpx.AsyncClient, comanda_id: str, motivo: str = "Llegó frío", **extra: Any
) -> httpx.Response:
    return await cliente.post(
        f"/api/comandas/{comanda_id}/devolucion", json={"motivo": motivo, **extra}
    )


async def _devoluciones_completas(e: Esc, comanda_id: str) -> list[asyncpg.Record]:
    async with e.pool.acquire() as conn:
        return await conn.fetch(
            "SELECT es_efectivo, monto, origen, motivo, autorizado_por, creado_por, creado "
            "FROM devoluciones_comanda WHERE comanda_id = $1 ORDER BY es_efectivo DESC",
            UUID(comanda_id),
        )


async def _admin_id(e: Esc) -> UUID:
    async with e.pool.acquire() as conn:
        return UUID(
            str(await conn.fetchval("SELECT id FROM usuarios WHERE email = $1", e.admin_email))
        )


async def test_devolver_entregada_no_regresa_stock_y_baja_el_esperado(esc: Esc) -> None:
    cid = await _cobrada(
        esc,
        pagos=[{"metodo_pago_id": str(esc.tarjeta), "monto": "70.00", "notas_pago": "Folio: 3"}],
    )
    await _entregar(esc, cid)
    assert await _stock(esc) == Decimal("9")
    tarjeta = await _nombre_tarjeta(esc)
    total_antes, _ = await _balance(esc)

    # Sin token: el mismo 403 que la cancelación, con el turno para el PIN.
    r = await _devolver(esc.cajero, cid)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "AUTORIZACION_ADMIN_REQUERIDA"
    assert r.json()["detail"]["turno_id"] == str(esc.apertura)
    assert tuple(await _comanda(esc, cid)) == ("T", True)

    r = await _devolver(esc.cajero, cid, token_pin_admin=await _token_admin(esc))
    assert r.status_code == 200, r.text
    assert r.json()["estado_actual"] == "C"

    # El producto ya se consumió: el stock no regresa ni hay reversión.
    assert await _stock(esc) == Decimal("9")
    assert await _reversiones(esc, cid) == 0
    assert tuple(await _comanda(esc, cid)) == ("C", False)

    async with esc.pool.acquire() as conn:
        motivo = await conn.fetchval(
            "SELECT motivo_cancelacion FROM comandas WHERE id = $1", UUID(cid)
        )
    assert motivo == "Llegó frío"
    devs = await _devoluciones_completas(esc, cid)
    assert len(devs) == 1
    d = devs[0]
    assert (d["es_efectivo"], d["monto"], d["origen"], d["motivo"]) == (
        False,
        Decimal("70.00"),
        "entregada",
        "Llegó frío",
    )
    assert d["autorizado_por"] == await _admin_id(esc)
    assert d["creado_por"] == esc.cajero_id
    assert d["creado"] is not None

    total, filas = await _balance(esc)
    assert (filas[tarjeta].esperado, filas[tarjeta].devoluciones) == (
        Decimal("0.00"),
        Decimal("70.00"),
    )
    assert total == total_antes - Decimal("70.00")

    # No se devuelve dos veces (ni se consume otro token).
    token = await _token_admin(esc)
    r = await _devolver(esc.cajero, cid, token_pin_admin=token)
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "DEVOLUCION_NO_APLICA"
    assert len(await _devoluciones_completas(esc, cid)) == 1
    # Tampoco se cancela después (ya está cancelada).
    assert (await _cancelar(esc.cajero, cid, token_pin_admin=token)).status_code == 409


async def test_devolver_entregada_en_efectivo_sale_del_cajon(esc: Esc) -> None:
    cid = await _cobrada(
        esc,
        pagos=[{"metodo_pago_id": str(esc.efectivo), "monto": "100.00", "notas_pago": ""}],
        cambio="30.00",
    )
    await _entregar(esc, cid)
    assert await _efectivo_esperado(esc) == (Decimal("1070.00"), Decimal("1070.00"))

    r = await _devolver(esc.cajero, cid, token_pin_admin=await _token_admin(esc))
    assert r.status_code == 200, r.text

    assert await _efectivo_esperado(esc) == (Decimal("1000.00"), Decimal("1000.00"))
    _, filas = await _balance(esc)
    assert filas["efectivo"].devoluciones == Decimal("70.00")
    assert await _stock(esc) == Decimal("9")


async def test_devolver_entregada_simultaneas_registran_una_vez(esc: Esc) -> None:
    from app.services import comanda_service

    cid = await _cobrada(esc)
    await _entregar(esc, cid)
    tokens = [await _token_admin(esc) for _ in range(4)]
    user = _usuario(esc.cajero_id, esc.sucursal)

    async def devolver(token: str) -> Any:
        async with esc.pool.acquire() as conn:
            return await comanda_service.devolver_entregada(conn, cid, user, "Duplicado", token)

    resultados = await asyncio.gather(*(devolver(t) for t in tokens), return_exceptions=True)
    exitos = [r for r in resultados if not isinstance(r, BaseException)]
    assert len(exitos) == 1, resultados
    assert len(await _devoluciones_completas(esc, cid)) == 1
    assert await _efectivo_esperado(esc) == (Decimal("1000.00"), Decimal("1000.00"))


async def test_devolver_entregada_exige_pin_de_admin_de_la_sucursal(esc: Esc) -> None:
    cid = await _cobrada(esc)
    await _entregar(esc, cid)

    async def validar(email: str, pin: str) -> httpx.Response:
        return await esc.cajero.post(
            "/api/turnos-caja/validar-pin-admin",
            json={"turno_id": str(esc.apertura), "admin_email": email, "pin": pin},
        )

    # Un cajero no autoriza aunque tenga PIN.
    r = await validar(esc.cajero_email, PIN_ADMIN)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "AUTORIZADOR_NO_VALIDO"
    # Ni el administrador de otra sucursal.
    r = await validar(esc.admin_otra_email, PIN_ADMIN)
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "AUTORIZADOR_NO_VALIDO"
    # PIN incorrecto del administrador correcto: no hay token.
    r = await validar(esc.admin_email, "0000")
    assert r.status_code in (401, 403), r.text
    assert "token_pin" not in r.json()
    # Y un token inventado no se acepta.
    r = await _devolver(esc.cajero, cid, token_pin_admin="token-inexistente")
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "PIN_TOKEN_REQUERIDO"

    assert tuple(await _comanda(esc, cid)) == ("T", True)
    assert await _devoluciones_completas(esc, cid) == []


async def test_devolucion_solo_aplica_a_entregadas_con_cobro(esc: Esc) -> None:
    # Una que sigue en cocina se cancela (y regresa su stock), no se devuelve.
    en_cocina = await _cobrada(esc)
    r = await _devolver(esc.cajero, en_cocina, token_pin_admin="x")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "DEVOLUCION_NO_APLICA"

    # Entregada sin cobros (comanda automática de evento): nada que devolver.
    sin_cobro = await _sin_cobro(esc)
    await _entregar(esc, sin_cobro)
    r = await _devolver(esc.cajero, sin_cobro, token_pin_admin="x")
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "COMANDA_SIN_PAGOS"

    # El motivo es obligatorio.
    assert (await _devolver(esc.cajero, en_cocina, motivo="")).status_code == 422
    assert (await _devolver(esc.cajero, en_cocina, motivo="   ")).status_code == 422

    # Cocina no maneja dinero.
    entregada = await _cobrada(esc)
    await _entregar(esc, entregada)
    r = await _devolver(esc.cocina, entregada, token_pin_admin=await _token_admin(esc))
    assert r.status_code == 403
    assert tuple(await _comanda(esc, entregada)) == ("T", True)


async def test_devolver_entregada_revierte_los_puntos_de_lealtad(esc: Esc) -> None:
    cid = await _cobrada(esc)
    await _entregar(esc, cid)
    async with esc.pool.acquire() as conn:
        lote = await conn.fetchval(
            "INSERT INTO lotes_puntos (sucursal_id, celular, comanda_id, puntos_otorgados, "
            "puntos_disponibles, fecha_caducidad) "
            "VALUES ($1, '5512345678', $2, 7, 7, now() + interval '30 days') RETURNING id",
            esc.sucursal,
            UUID(cid),
        )

    r = await _devolver(esc.cajero, cid, token_pin_admin=await _token_admin(esc))
    assert r.status_code == 200, r.text

    async with esc.pool.acquire() as conn:
        disponibles = await conn.fetchval(
            "SELECT puntos_disponibles FROM lotes_puntos WHERE id = $1", lote
        )
    assert disponibles == 0


def _texto_pdf(pdf: bytes) -> bytes:
    """Contenido de los flujos del PDF (ReportLab los guarda en ASCII85 +
    Flate), decodificados, para buscar texto."""
    import base64
    import re
    import zlib

    texto = b""
    for flujo in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        try:
            datos = flujo.strip().removesuffix(b"~>")
            texto += zlib.decompress(base64.a85decode(datos))
        except (ValueError, zlib.error):
            texto += flujo
    return texto


async def test_detalle_y_pdf_del_arqueo_muestran_las_devoluciones(esc: Esc) -> None:
    from app.repositories.caja_repository import crear_cierre_caja
    from app.services import pdf_service, turnos_caja_service

    cancelada = await _cobrada(
        esc,
        pagos=[{"metodo_pago_id": str(esc.tarjeta), "monto": "70.00", "notas_pago": "Folio: 4"}],
    )
    r = await _cancelar(esc.cajero, cancelada, token_pin_admin=await _token_admin(esc))
    assert r.status_code == 200, r.text
    entregada = await _cobrada(esc)
    await _entregar(esc, entregada)
    token = await _token_admin(esc)
    r = await _devolver(esc.cajero, entregada, motivo="Producto equivocado", token_pin_admin=token)
    assert r.status_code == 200, r.text

    tarjeta = await _nombre_tarjeta(esc)
    admin_id = await _admin_id(esc)
    async with esc.pool.acquire() as conn:
        tickets = [
            str(row["ticket_numero"])
            for row in await conn.fetch(
                "SELECT ticket_numero FROM comandas WHERE id = ANY($1::uuid[])",
                [UUID(cancelada), UUID(entregada)],
            )
        ]
        cierre = await crear_cierre_caja(
            conn,
            apertura_caja_id=str(esc.apertura),
            tipo_cierre="NORMAL",
            monto_sistema=Decimal("1000.00"),
            monto_cierre=Decimal("1000.00"),
            cajero_id=str(esc.cajero_id),
            administrador_id=str(admin_id),
            creado_por=str(admin_id),
        )
        detalle = await turnos_caja_service.obtener_detalle(conn, str(cierre["id"]))

    por_origen = {d.origen: d for d in detalle.devoluciones}
    assert set(por_origen) == {"cancelacion", "entregada"}
    assert por_origen["cancelacion"].monto == Decimal("70.00")
    assert not por_origen["cancelacion"].es_efectivo
    assert por_origen["cancelacion"].motivo == "Cliente se arrepintió"
    assert por_origen["entregada"].es_efectivo
    assert por_origen["entregada"].motivo == "Producto equivocado"
    assert por_origen["entregada"].autorizado_por_nombre
    assert por_origen["entregada"].creado_por_nombre
    filas = {b.metodo: b for b in detalle.balance_por_metodo}
    assert filas["efectivo"].devoluciones == Decimal("70.00")
    assert filas[tarjeta].devoluciones == Decimal("70.00")

    texto = _texto_pdf(pdf_service.generar_pdf_arqueo(detalle))
    assert b"Devoluciones a Clientes" in texto
    assert b"Producto equivocado" in texto
    for ticket in tickets:
        assert ticket.encode() in texto
    assert b"-$ 70.00" in texto
