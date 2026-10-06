"""Escenario de POS para las pruebas de caja con BD real: sucursal, cajero,
caja, turno horario, apertura ABIERTA con $500 de fondo y un producto de
$95. Cada módulo de prueba
lo envuelve en su fixture `pos` con crear_pos."""

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import asyncpg
from app.schemas.pagos import DetalleVentaIn, PagoCompletoRequest, PaymentItem
from app.services import pago_service

# Lo que se espera a que una operación bloqueada siga bloqueada.
ESPERA = 0.4


@dataclass
class Pos:
    sucursal: uuid.UUID
    cajero: uuid.UUID
    caja: uuid.UUID
    apertura: str
    producto: uuid.UUID
    efectivo: uuid.UUID
    tarjeta: uuid.UUID


async def crear_pos(pool: asyncpg.Pool) -> Pos:
    sufijo = uuid.uuid4().hex[:8]
    async with pool.acquire() as conn:
        sucursal = await conn.fetchval(
            "INSERT INTO public.sucursales (nombre, clave) VALUES ($1, $2) RETURNING id",
            f"Sucursal POS {sufijo}",
            sufijo.upper(),
        )
        cajero = await conn.fetchval(
            "INSERT INTO public.usuarios (email, password_hash, nombre_completo, rol) "
            "VALUES ($1, 'x', $2, 3) RETURNING id",
            f"cajero.pos.{sufijo}@test.local",
            f"Cajero {sufijo}",
        )
        caja = await conn.fetchval(
            "INSERT INTO public.cajas (sucursal_id, codigo, nombre, numero) "
            "VALUES ($1, $2, $3, 1) RETURNING id",
            sucursal,
            f"C-{sufijo}",
            f"Caja Patria {sufijo}",
        )
        turno = await conn.fetchval(
            "INSERT INTO public.turnos (nombre, hora_inicio, hora_fin) "
            "VALUES ($1, '08:00', '16:00') RETURNING id",
            f"Turno {sufijo}",
        )
        apertura = await conn.fetchval(
            "INSERT INTO public.apertura_caja (caja_id, cajero_id, turno_id, fondo_inicial) "
            "VALUES ($1, $2, $3, 500) RETURNING id",
            caja,
            cajero,
            turno,
        )
        producto = await conn.fetchval(
            "INSERT INTO public.productos (nombre, precio_unitario, tipo, sucursal_id, activo) "
            "VALUES ($1, 95.00, 'A', $2, TRUE) RETURNING id",
            f"Pizza {sufijo}",
            sucursal,
        )
        efectivo = await conn.fetchval("SELECT id FROM public.metodos_pago WHERE tipo = 'E'")
        tarjeta = await conn.fetchval("SELECT id FROM public.metodos_pago WHERE tipo = 'T'")
    return Pos(sucursal, cajero, caja, str(apertura), producto, efectivo, tarjeta)


def _venta(p: Pos, pagos: list[tuple[uuid.UUID, str]], cambio: str = "0") -> PagoCompletoRequest:
    return PagoCompletoRequest(
        total_final=Decimal("95.00"),
        detalles_comanda=[
            DetalleVentaIn(
                producto_id=str(p.producto),
                nombre="Pizza",
                cantidad=1,
                precio_unitario=Decimal("95.00"),
                subtotal=Decimal("95.00"),
            )
        ],
        # Con referencia: otra prueba hace que la tarjeta la exija.
        pagos=[
            PaymentItem(metodo_pago_id=m, monto=Decimal(monto), notas_pago="REF-1")
            for m, monto in pagos
        ],
        cambio=Decimal(cambio),
    )


async def _cobrar(conn: asyncpg.Connection, p: Pos, venta: PagoCompletoRequest) -> Any:
    return await pago_service.completar_pago(conn, venta, p.cajero, p.sucursal, p.apertura)


async def _estado_y_ventas(pool: asyncpg.Pool, apertura: str) -> tuple[str, int]:
    async with pool.acquire() as conn:
        estado = await conn.fetchval(
            "SELECT estado FROM public.apertura_caja WHERE id = $1", uuid.UUID(apertura)
        )
        ventas = await conn.fetchval(
            "SELECT COUNT(*) FROM public.movimientos_caja "
            "WHERE apertura_caja_id = $1 AND tipo_movimiento = 'O'",
            uuid.UUID(apertura),
        )
    return estado, ventas
