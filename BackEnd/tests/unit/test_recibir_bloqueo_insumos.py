"""N3: `recibir` bloquea de una vez los insumos de la recepción, en orden de
id, antes de mover stock. Antes cada UPDATE de stock tomaba el bloqueo en el
orden de las líneas (por nombre) y dos recepciones podían trabarse. La prueba
concurrente está en tests/db/test_recibir_orden_bloqueo_pg.py."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.repositories import insumo_repository
from app.services import compra_service


class _Conn:
    def __init__(self) -> None:
        self.sql: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.sql.append((sql, args))
        return "SELECT 2"


async def test_n3_bloquear_insumos_ordena_por_id_y_sin_repetidos() -> None:
    conn = _Conn()
    a, b, c = sorted([uuid4(), uuid4(), uuid4()])

    await insumo_repository.bloquear_por_ids(conn, [c, a, b, a])  # type: ignore[arg-type]

    sql, args = conn.sql[0]
    assert "ORDER BY id" in sql and "FOR UPDATE" in sql
    assert args[0] == [a, b, c]


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: Any) -> bool:
        return False


async def test_n3_recibir_bloquea_los_insumos_antes_de_mover_stock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Los insumos se bloquean de una vez (en orden de id) antes del primer
    UPDATE de stock, no uno por uno en el orden de las líneas."""
    eventos: list[Any] = []
    svc = "app.services.compra_service"
    detalles = [
        {
            "id": uuid4(),
            "insumo_id": insumo_id,
            "unidad_medida_id": uuid4(),
            "presentacion_id": None,
            "cantidad": Decimal("1"),
            "cantidad_recibida": Decimal("0"),
            "costo_unitario": Decimal("1"),
            "insumo_nombre": "Pan",
        }
        for insumo_id in (UUID(int=3), UUID(int=1), UUID(int=2))
    ]
    conn = MagicMock()
    conn.transaction = lambda: _Tx()
    monkeypatch.setattr(
        f"{svc}.compra_repository.bloquear",
        AsyncMock(return_value={"id": uuid4(), "estado": "P", "sucursal_id": uuid4()}),
    )
    monkeypatch.setattr(
        f"{svc}.compra_repository.listar_detalles", AsyncMock(return_value=detalles)
    )

    async def _bloquear(_conn: Any, ids: list[UUID]) -> None:
        eventos.append(("bloquear", ids))

    async def _ajustar(_conn: Any, insumo_id: UUID, _delta: Decimal) -> Decimal:
        eventos.append(("ajustar", insumo_id))
        return Decimal("1")

    monkeypatch.setattr(f"{svc}.insumo_repository.bloquear_por_ids", _bloquear)
    monkeypatch.setattr(f"{svc}.insumo_repository.ajustar_stock", _ajustar)
    monkeypatch.setattr(f"{svc}.insumo_repository.obtener", AsyncMock(return_value={"id": 1}))
    monkeypatch.setattr(
        f"{svc}._validar_y_calcular_base", AsyncMock(return_value=(Decimal("1"), Decimal("1")))
    )
    monkeypatch.setattr(f"{svc}.costeo_service.registrar_entrada", AsyncMock())
    monkeypatch.setattr(f"{svc}.movimiento_inventario_repository.registrar", AsyncMock())
    monkeypatch.setattr(f"{svc}.compra_repository.sumar_recepcion_linea", AsyncMock())
    monkeypatch.setattr(f"{svc}.compra_repository.marcar_estado", AsyncMock(return_value={}))
    monkeypatch.setattr(f"{svc}._construir_out", AsyncMock(return_value=MagicMock()))

    await compra_service.recibir(conn, uuid4(), uuid4())

    assert eventos[0][0] == "bloquear"
    assert set(eventos[0][1]) == {UUID(int=1), UUID(int=2), UUID(int=3)}
    assert [e[0] for e in eventos[1:]] == ["ajustar", "ajustar", "ajustar"]
