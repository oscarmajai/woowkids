"""Casos de borde al dar de alta una sucursal completa por la API."""

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.repositories import caja_repository, producto_repository

FILA = {
    "id": uuid4(),
    "nombre": "Estancia",
    "precio_unitario": Decimal("0"),
    "tipo": "E",
    "sucursal_id": uuid4(),
    "activo": True,
    "es_combo": False,
}


async def test_crear_producto_de_estancia_serializa_los_tramos_como_json() -> None:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=FILA)
    tramos = [{"min_horas": 1, "max_horas": 2, "precio": 120}]

    await producto_repository.crear(
        conn,
        nombre="Estancia",
        precio_unitario=Decimal("0"),
        tipo="E",
        sucursal_id=uuid4(),
        descripcion=None,
        imagen=None,
        config_estancia=tramos,
    )

    args = conn.fetchrow.call_args.args
    assert json.dumps(tramos) in args, "config_estancia debe viajar como JSON, no como lista"


async def test_caja_por_id_con_uuid_invalido_no_consulta() -> None:
    conn = MagicMock()
    conn.fetchrow = AsyncMock()

    assert await caja_repository.get_caja_por_id(conn, str(uuid4()), "no-es-uuid") is None
    conn.fetchrow.assert_not_called()


async def test_caja_por_id_filtra_por_sucursal() -> None:
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value=None)
    sucursal, caja = str(uuid4()), str(uuid4())

    assert await caja_repository.get_caja_por_id(conn, sucursal, caja) is None
    sql = conn.fetchrow.call_args.args[0]
    assert "sucursal_id = $1" in sql and "id = $2" in sql
