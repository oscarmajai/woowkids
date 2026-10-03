"""Movimientos de caja de un turno contra PostgreSQL real: el cambio dado y los
ingresos de efectivo tienen su propio tipo y nunca cuentan como venta, el
balance del cierre los resta/suma al efectivo esperado, los retiros no pueden
dejar la caja en negativo y 'efectivo' se reconoce por metodos_pago.tipo='E'
y no por su nombre editable.

Migrados de tests/integration (que dependían de IDs fijos de la BD compartida
de desarrollo, N16): cada prueba crea su propia sucursal, cajero, caja, turno
y apertura con fondo inicial de $1,000.
"""

import json
import uuid
from decimal import Decimal

import asyncpg
import pytest
from app.repositories import caja_repository, metodos_pago_repository
from app.schemas.caja import IngresoEfectivoCreate, RetiroParcialCreate, TipoDestinatario
from app.services import turnos_caja_service
from app.services.turnos_caja_service import EfectivoInsuficienteError, crear_retiro
from fastapi import HTTPException

from tests.db.conftest import Escenario, crear_apertura

FONDO = Decimal("1000.00")


async def _efectivo_id(conn: asyncpg.Connection) -> str:
    return str(await conn.fetchval("SELECT id FROM public.metodos_pago WHERE tipo = 'E'"))


async def _venta_efectivo(conn: asyncpg.Connection, apertura_id: str, monto: str) -> str:
    referencia = str(uuid.uuid4())
    await caja_repository.registrar_movimiento_caja(
        conn,
        apertura_caja_id=apertura_id,
        tipo_movimiento="O",
        referencia_id=referencia,
        metodo_pago_id=await _efectivo_id(conn),
        monto=Decimal(monto),
    )
    return referencia


async def _esperado(conn: asyncpg.Connection, apertura_id: str) -> Decimal:
    apertura = await caja_repository.get_apertura_por_id(conn, apertura_id)
    assert apertura is not None
    total_esperado, _, _, _ = await turnos_caja_service._calcular_balance(
        conn, apertura, apertura_id
    )
    return total_esperado


def _retiro(apertura_id: str, monto: str) -> RetiroParcialCreate:
    return RetiroParcialCreate(
        apertura_caja_id=apertura_id,
        tipo_destinatario=TipoDestinatario.EMPLEADO,
        monto=Decimal(monto),
    )


# ── Cambio ───────────────────────────────────────────────────────────────────


async def test_cambio_no_cuenta_como_venta_y_resta_del_esperado(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        referencia = await _venta_efectivo(conn, apertura, "200.00")
        await caja_repository.registrar_cambio_caja(
            conn, apertura_caja_id=apertura, referencia_id=referencia, monto=Decimal("80.00")
        )

        assert await caja_repository.sumar_total_ventas_apertura(conn, apertura) == Decimal(
            "200.00"
        )
        assert await caja_repository.sumar_ventas_efectivo_apertura(conn, apertura) == Decimal(
            "200.00"
        )
        assert await caja_repository.sumar_cambio_apertura(conn, apertura) == Decimal("80.00")
        fila = await conn.fetchrow(
            "SELECT metodo_pago_id, monto FROM public.movimientos_caja "
            "WHERE apertura_caja_id = $1 AND tipo_movimiento = 'C'",
            uuid.UUID(apertura),
        )
        assert fila["metodo_pago_id"] is None  # mismo criterio que el retiro parcial
        assert fila["monto"] == Decimal("80.00")

        # fondo 1000 + venta 200 - cambio 80
        assert await _esperado(conn, apertura) == Decimal("1120.00")


async def test_listar_cambios_por_apertura(pool: asyncpg.Pool, escenario: Escenario) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        assert await caja_repository.listar_cambios_por_apertura(conn, apertura) == []
        await caja_repository.registrar_cambio_caja(
            conn,
            apertura_caja_id=apertura,
            referencia_id=str(uuid.uuid4()),
            monto=Decimal("80.00"),
        )
        cambios = await caja_repository.listar_cambios_por_apertura(conn, apertura)
    assert len(cambios) == 1
    assert cambios[0]["monto"] == Decimal("80.00")
    assert "id" in cambios[0] and "creado" in cambios[0]


async def test_detalle_de_arqueo_incluye_los_cambios_del_turno(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        await caja_repository.registrar_cambio_caja(
            conn,
            apertura_caja_id=apertura,
            referencia_id=str(uuid.uuid4()),
            monto=Decimal("80.00"),
        )
        await caja_repository.actualizar_conteo_apertura(
            conn,
            apertura,
            FONDO,
            json.dumps({"desglose_efectivo": {"total": 1000.00}, "metodos_pago": []}),
        )
        cierre = await caja_repository.crear_cierre_caja(
            conn,
            apertura_caja_id=apertura,
            tipo_cierre="NORMAL",
            monto_sistema=FONDO,
            monto_cierre=FONDO,
            cajero_id=str(escenario.usuario_id),
            administrador_id=str(escenario.usuario_id),
        )
        detalle = await turnos_caja_service.obtener_detalle(conn, str(cierre["id"]))
    assert [c.monto for c in detalle.cambios] == [Decimal("80.00")]


# ── Ingreso de efectivo ──────────────────────────────────────────────────────


async def test_ingreso_no_cuenta_como_venta_y_suma_al_esperado(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        await _venta_efectivo(conn, apertura, "200.00")
        await caja_repository.registrar_ingreso_efectivo(
            conn, apertura_caja_id=apertura, referencia_id=apertura, monto=Decimal("500.00")
        )

        assert await caja_repository.sumar_total_ventas_apertura(conn, apertura) == Decimal(
            "200.00"
        )
        assert await caja_repository.sumar_ventas_efectivo_apertura(conn, apertura) == Decimal(
            "200.00"
        )
        assert await caja_repository.sumar_ingresos_por_apertura(conn, apertura) == Decimal(
            "500.00"
        )
        fila = await conn.fetchrow(
            "SELECT metodo_pago_id, monto FROM public.movimientos_caja "
            "WHERE apertura_caja_id = $1 AND tipo_movimiento = 'I'",
            uuid.UUID(apertura),
        )
        assert fila["metodo_pago_id"] is None
        assert fila["monto"] == Decimal("500.00")

        # fondo 1000 + venta 200 + ingreso 500
        assert await _esperado(conn, apertura) == Decimal("1700.00")


async def test_crear_ingreso_sobre_el_turno_abierto(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    payload = IngresoEfectivoCreate(apertura_caja_id=apertura, monto=Decimal("300.00"))
    async with pool.acquire() as conn:
        resultado = await turnos_caja_service.crear_ingreso(
            conn, str(escenario.usuario_id), payload
        )
    assert resultado.apertura_caja_id == apertura
    assert resultado.monto == Decimal("300.00")


async def test_crear_ingreso_con_el_turno_en_conteo_da_409(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO, estado="EN_CORTE")
    payload = IngresoEfectivoCreate(apertura_caja_id=apertura, monto=Decimal("300.00"))
    async with pool.acquire() as conn:
        with pytest.raises(HTTPException) as exc_info:
            await turnos_caja_service.crear_ingreso(conn, str(escenario.usuario_id), payload)
        assert exc_info.value.status_code == 409
        assert await caja_repository.sumar_ingresos_por_apertura(conn, apertura) == Decimal("0")


# ── Retiros parciales ────────────────────────────────────────────────────────


async def test_retiro_mayor_al_efectivo_disponible_se_rechaza(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        with pytest.raises(EfectivoInsuficienteError):
            await crear_retiro(conn, str(escenario.usuario_id), _retiro(apertura, "1500.00"))
        assert await caja_repository.sumar_retiros_por_apertura(conn, apertura) == Decimal("0")


async def test_retiro_exactamente_igual_al_disponible_se_permite(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        resp = await crear_retiro(conn, str(escenario.usuario_id), _retiro(apertura, "1000.00"))
    assert resp.monto == Decimal("1000.00")


async def test_retiro_considera_los_retiros_previos_del_turno(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    # Dos retiros de 600 sobre un fondo de 1000: el segundo ya no cabe aunque
    # 600 <= 1000, porque el primero dejó solo 400 disponibles.
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        await crear_retiro(conn, str(escenario.usuario_id), _retiro(apertura, "600.00"))
        with pytest.raises(EfectivoInsuficienteError):
            await crear_retiro(conn, str(escenario.usuario_id), _retiro(apertura, "600.00"))
        assert await caja_repository.sumar_retiros_por_apertura(conn, apertura) == Decimal("600.00")


# ── Identidad del efectivo ───────────────────────────────────────────────────


async def test_obtener_ids_por_tipo_resuelve_la_fila_del_catalogo(
    pool: asyncpg.Pool,
) -> None:
    async with pool.acquire() as conn:
        efectivo = await conn.fetchval("SELECT id FROM public.metodos_pago WHERE tipo = 'E'")
        tarjeta = await conn.fetchval("SELECT id FROM public.metodos_pago WHERE tipo = 'T'")
        assert await metodos_pago_repository.obtener_ids_por_tipo(conn, "E") == {efectivo}
        assert await metodos_pago_repository.obtener_ids_por_tipo(conn, "T") == {tarjeta}
        assert await metodos_pago_repository.obtener_ids_por_tipo(conn, "X") == set()


async def test_efectivo_renombrado_se_sigue_reconociendo_por_su_tipo(
    pool: asyncpg.Pool, escenario: Escenario
) -> None:
    """El nombre del catálogo global lo puede editar un AdministradorSistema;
    el cálculo del efectivo depende de tipo='E'. El renombre va dentro de una
    transacción que se revierte para no afectar al resto de las pruebas."""
    apertura = await crear_apertura(pool, escenario, FONDO)
    async with pool.acquire() as conn:
        tx = conn.transaction()
        await tx.start()
        try:
            await metodos_pago_repository.actualizar_catalogo(
                conn, uuid.UUID(await _efectivo_id(conn)), {"nombre": "Caja Chica"}
            )
            await _venta_efectivo(conn, apertura, "300.00")

            assert await caja_repository.sumar_ventas_efectivo_apertura(conn, apertura) == Decimal(
                "300.00"
            )
            fila_apertura = await caja_repository.get_apertura_por_id(conn, apertura)
            assert fila_apertura is not None
            _, _, _, balance = await turnos_caja_service._calcular_balance(
                conn, fila_apertura, apertura
            )
            fila_efectivo = next(f for f in balance if f.metodo == "efectivo")
            assert fila_efectivo.esperado == Decimal("1300.00")
            # Sin una fila duplicada "caja chica" tratada como método aparte.
            assert not any(f.metodo == "caja chica" for f in balance)
        finally:
            await tx.rollback()
