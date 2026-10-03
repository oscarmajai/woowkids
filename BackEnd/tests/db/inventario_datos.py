"""Datos de prueba de inventario y compras (insumos, proveedores, compras)
compartidos por las pruebas con PostgreSQL real. Todo pasa por los services,
igual que en la API."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import asyncpg
from app.schemas.auth import TokenData
from app.schemas.compra import CompraCrear, DetalleCompraItem
from app.schemas.insumo import InsumoCrear
from app.services import compra_service, insumo_service

from tests.db.conftest import Escenario


def token(esc: Escenario) -> TokenData:
    return TokenData(
        sub=str(esc.usuario_id),
        email="inventario@test.local",
        role="3",
        branch_id=esc.sucursal_id,
        jti=uuid.uuid4().hex,
        exp=datetime.now(UTC) + timedelta(hours=1),
    )


async def unidad(conn: asyncpg.Connection, codigo: str) -> uuid.UUID:
    unidad_id: uuid.UUID = await conn.fetchval(
        "SELECT id FROM public.unidades_medida WHERE codigo = $1", codigo
    )
    return unidad_id


async def crear_insumo(
    conn: asyncpg.Connection,
    esc: Escenario,
    *,
    codigo_unidad: str = "pza",
    stock: str = "0",
    costo: str | None = None,
    nombre: str | None = None,
) -> uuid.UUID:
    unidad_id = await unidad(conn, codigo_unidad)
    insumo = await insumo_service.crear(
        conn,
        InsumoCrear(
            sucursal_id=esc.sucursal_id,
            nombre=nombre or f"Insumo {uuid.uuid4().hex[:8]}",
            unidad_base_id=unidad_id,
            unidad_compra_id=unidad_id,
            stock_inicial=Decimal(stock),
            costo_unitario=Decimal(costo) if costo is not None else None,
        ),
        token(esc),
    )
    return insumo.id


async def crear_proveedor(conn: asyncpg.Connection, esc: Escenario) -> uuid.UUID:
    proveedor_id: uuid.UUID = await conn.fetchval(
        "INSERT INTO public.proveedores (sucursal_id, nombre) VALUES ($1, $2) RETURNING id",
        esc.sucursal_id,
        f"Proveedor {uuid.uuid4().hex[:8]}",
    )
    return proveedor_id


def linea(
    insumo_id: uuid.UUID, unidad_id: uuid.UUID, cantidad: str, costo: str
) -> DetalleCompraItem:
    return DetalleCompraItem(
        insumo_id=insumo_id,
        unidad_medida_id=unidad_id,
        cantidad=Decimal(cantidad),
        costo_unitario=Decimal(costo),
    )


async def crear_compra(
    conn: asyncpg.Connection,
    esc: Escenario,
    lineas: list[DetalleCompraItem],
    proveedor_id: uuid.UUID | None = None,
) -> uuid.UUID:
    compra = await compra_service.crear(
        conn,
        CompraCrear(
            sucursal_id=esc.sucursal_id,
            proveedor_id=proveedor_id or await crear_proveedor(conn, esc),
            detalles=lineas,
        ),
        esc.usuario_id,
    )
    return compra.id
