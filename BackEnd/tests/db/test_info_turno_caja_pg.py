"""Información del turno de caja contra PostgreSQL real.

- El turno cuenta tickets (un pago mixto es una venta) y lo vendido va neto
  del cambio. Efectivo esperado y ventas por método.
- Las notas de la apertura y el motivo del ingreso se guardan."""

import uuid
from decimal import Decimal

import asyncpg
import pytest_asyncio
from app.repositories import caja_repository
from app.schemas.caja import IngresoEfectivoCreate
from app.services import turnos_caja_service

from tests.db.pos_fixtures import Pos, _cobrar, _venta, crear_pos


@pytest_asyncio.fixture
async def pos(pool: asyncpg.Pool) -> Pos:
    return await crear_pos(pool)


# ── Ventas y efectivo del turno ───────────────────────────────────────────────


async def test_el_turno_cuenta_tickets_y_lo_vendido_va_neto_del_cambio(
    pool: asyncpg.Pool, pos: Pos
) -> None:
    async with pool.acquire() as conn:
        # Pago mixto: 50 en tarjeta + 100 en efectivo, 55 de cambio → 1 ticket de 95.
        await _cobrar(conn, pos, _venta(pos, [(pos.tarjeta, "50"), (pos.efectivo, "100")], "55"))
        await _cobrar(conn, pos, _venta(pos, [(pos.efectivo, "95")]))
        turno = await turnos_caja_service.obtener_turno_activo(conn, str(pos.cajero))

    assert turno.numero_ventas == 2  # antes 3 (contaba pagos)
    assert turno.total_ventas == Decimal("245.00")  # recibido
    assert turno.total_vendido == Decimal("190.00")  # aplicado
    # 500 de fondo + 195 en efectivo - 55 de cambio.
    assert turno.efectivo_esperado == Decimal("640.00")
    por_metodo = {v.metodo: v.total for v in turno.ventas_por_metodo}
    assert por_metodo["efectivo"] == Decimal("140.00")
    assert sum(por_metodo.values()) == turno.total_vendido
    assert turno.caja_nombre is not None and turno.caja_nombre.startswith("Caja Patria")


async def test_pagos_de_una_reservacion_cuentan_como_una_venta(
    pool: asyncpg.Pool, pos: Pos
) -> None:
    async with pool.acquire() as conn:
        tipo = await conn.fetchval(
            "INSERT INTO public.tipos_evento (nombre, sucursal_id) VALUES ('Cumpleaños', $1) "
            "RETURNING id",
            pos.sucursal,
        )
        paquete = await conn.fetchval(
            """INSERT INTO public.paquetes (sucursal_id, nombre, min_invitados, max_invitados,
                   precio_base, precio_hora_pulsera, anticipo_porcentaje)
               VALUES ($1, 'Premium', 10, 30, 6900, 60, 40) RETURNING id""",
            pos.sucursal,
        )
        reservacion = await conn.fetchval(
            """INSERT INTO public.reservaciones (sucursal_id, tipo_evento_id, paquete_id,
                   nombre_cliente, telefono_cliente, fecha_evento, hora_inicio, hora_fin,
                   numero_personas, precio_base, precio_total, anticipo, estado)
               VALUES ($1, $2, $3, 'Fiesta', '3312345678', CURRENT_DATE + 30, '10:00',
                       '14:00', 20, 6900, 6900, 2760, 'confirmada')
               RETURNING id""",
            pos.sucursal,
            tipo,
            paquete,
        )
        # Anticipo en dos pagos (efectivo + tarjeta) de la misma reservación.
        for monto in ("100", "50"):
            pago_id = await conn.fetchval(
                "INSERT INTO public.pagos_reservacion (reservacion_id, metodo_pago_id, monto) "
                "VALUES ($1, $2, $3) RETURNING id",
                reservacion,
                pos.efectivo,
                Decimal(monto),
            )
            await caja_repository.registrar_movimiento_caja(
                conn,
                apertura_caja_id=pos.apertura,
                tipo_movimiento="R",
                referencia_id=str(pago_id),
                metodo_pago_id=str(pos.efectivo),
                monto=Decimal(monto),
            )
        assert await caja_repository.contar_ventas_apertura(conn, pos.apertura) == 1


# ── Notas de apertura y motivo del ingreso ───────────────────────────────────


async def test_se_guardan_las_notas_de_apertura_y_el_motivo_del_ingreso(
    pool: asyncpg.Pool, pos: Pos
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.apertura_caja SET estado = 'CERRADA' WHERE id = $1",
            uuid.UUID(pos.apertura),
        )
        turno_id = await conn.fetchval("SELECT id FROM public.turnos LIMIT 1")
        nueva = await caja_repository.crear_apertura_caja(
            conn,
            caja_id=str(pos.caja),
            cajero_id=str(pos.cajero),
            turno_id=str(turno_id),
            fondo_inicial=Decimal("300"),
            observaciones_apertura="Fondo con monedas de $10",
        )
        apertura = str(nueva["id"])
        await turnos_caja_service.crear_ingreso(
            conn,
            str(pos.cajero),
            IngresoEfectivoCreate(
                apertura_caja_id=apertura, monto=Decimal("200"), observaciones="Más cambio"
            ),
        )
        turno = await turnos_caja_service.obtener_turno_activo(conn, str(pos.cajero))
        ingresos = await caja_repository.listar_ingresos_por_apertura(conn, apertura)

    assert nueva["observaciones_apertura"] == "Fondo con monedas de $10"
    assert turno.observaciones_apertura == "Fondo con monedas de $10"
    assert turno.efectivo_esperado == Decimal("500.00")
    assert [(i["monto"], i["observaciones"]) for i in ingresos] == [
        (Decimal("200.00"), "Más cambio")
    ]
