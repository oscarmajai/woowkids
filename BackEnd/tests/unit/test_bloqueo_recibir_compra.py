"""Recibir / cancelar / editar una compra la bloquean (FOR UPDATE) dentro de
la transacción y releen estado y detalles después del bloqueo; marcar_estado
solo transiciona desde el estado previo esperado. Sin BD: un conn falso registra
el orden. La prueba de concurrencia real está en tests/db/test_carrera_compras.py."""

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.exceptions import Conflicto
from app.repositories import compra_repository
from app.services import compra_service

SVC = "app.services.compra_service"
COMPRA_ID = uuid4()
USER_ID = uuid4()


class _Tx:
    def __init__(self, eventos: list[str]) -> None:
        self.eventos = eventos

    async def __aenter__(self) -> None:
        self.eventos.append("BEGIN")

    async def __aexit__(self, exc_type: Any, *_: Any) -> bool:
        self.eventos.append("ROLLBACK" if exc_type else "COMMIT")
        return False


class FakeConn:
    def __init__(self, resultado_execute: str = "UPDATE 1") -> None:
        self.eventos: list[str] = []
        self.sql: list[tuple[str, tuple[Any, ...]]] = []
        self.resultado_execute = resultado_execute

    def transaction(self) -> _Tx:
        return _Tx(self.eventos)

    async def fetchrow(self, sql: str, *args: Any) -> None:
        self.sql.append((sql, args))
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        self.sql.append((sql, args))
        return self.resultado_execute


def _registra(conn: FakeConn, nombre: str, retorno: Any = None) -> AsyncMock:
    async def _fn(*_a: Any, **_k: Any) -> Any:
        conn.eventos.append(nombre)
        return retorno

    return AsyncMock(side_effect=_fn)


def _compra(estado: str) -> dict[str, Any]:
    return {"id": COMPRA_ID, "estado": estado, "sucursal_id": uuid4()}


def _detalle(cantidad: str, recibida: str) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "insumo_id": uuid4(),
        "unidad_medida_id": uuid4(),
        "presentacion_id": None,
        "cantidad": Decimal(cantidad),
        "cantidad_recibida": Decimal(recibida),
        "costo_unitario": Decimal("0.5"),
    }


def _parchear_recepcion(monkeypatch: pytest.MonkeyPatch, conn: FakeConn, estado: str) -> AsyncMock:
    """Parchea todo lo que toca recibir; devuelve el mock de marcar_estado."""
    monkeypatch.setattr(
        f"{SVC}.compra_repository.obtener",
        AsyncMock(side_effect=AssertionError("se leyó la compra sin bloqueo")),
    )
    monkeypatch.setattr(
        f"{SVC}.compra_repository.bloquear", _registra(conn, "bloquear", _compra(estado))
    )
    detalles = [_detalle("10", "0")]
    monkeypatch.setattr(
        f"{SVC}.compra_repository.listar_detalles", _registra(conn, "listar_detalles", detalles)
    )
    monkeypatch.setattr(f"{SVC}.insumo_repository.obtener", AsyncMock(return_value={"id": 1}))
    monkeypatch.setattr(
        f"{SVC}._validar_y_calcular_base",
        AsyncMock(return_value=(Decimal("10"), Decimal("0.5"))),
    )
    monkeypatch.setattr(
        f"{SVC}.insumo_repository.ajustar_stock", _registra(conn, "ajustar_stock", Decimal("10"))
    )
    monkeypatch.setattr(f"{SVC}.costeo_service.registrar_entrada", AsyncMock())
    monkeypatch.setattr(f"{SVC}.movimiento_inventario_repository.registrar", AsyncMock())

    async def _sumar(*_a: Any, **_k: Any) -> None:
        conn.eventos.append("sumar_recepcion")
        detalles[0]["cantidad_recibida"] = detalles[0]["cantidad"]

    monkeypatch.setattr(
        f"{SVC}.compra_repository.sumar_recepcion_linea", AsyncMock(side_effect=_sumar)
    )
    marcar = _registra(conn, "marcar_estado", _compra("R"))
    monkeypatch.setattr(f"{SVC}.compra_repository.marcar_estado", marcar)
    monkeypatch.setattr(f"{SVC}._construir_out", AsyncMock(return_value=MagicMock()))
    return marcar


async def test_recibir_bloquea_la_compra_y_relee_los_detalles_dentro_de_la_transaccion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    marcar = _parchear_recepcion(monkeypatch, conn, "P")

    await compra_service.recibir(conn, COMPRA_ID, USER_ID)  # type: ignore[arg-type]

    assert conn.eventos == [
        "BEGIN",
        "bloquear",
        "listar_detalles",
        "ajustar_stock",
        "sumar_recepcion",
        "listar_detalles",
        "marcar_estado",
        "COMMIT",
    ]
    assert marcar.call_args.kwargs["estados_previos"] == ("P", "PARCIAL")


@pytest.mark.parametrize(
    ("estado", "mensaje"),
    [("R", "La compra ya fue recibida."), ("C", "La compra está cancelada.")],
)
async def test_recibir_una_compra_ya_recibida_o_cancelada_responde_409_sin_tocar_stock(
    monkeypatch: pytest.MonkeyPatch, estado: str, mensaje: str
) -> None:
    conn = FakeConn()
    _parchear_recepcion(monkeypatch, conn, estado)

    with pytest.raises(Conflicto) as exc:
        await compra_service.recibir(conn, COMPRA_ID, USER_ID)  # type: ignore[arg-type]

    assert exc.value.status_code == 409
    assert exc.value.detail["message"] == mensaje
    assert conn.eventos == ["BEGIN", "bloquear", "ROLLBACK"]


async def test_cancelar_bloquea_la_compra_dentro_de_la_transaccion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConn()
    monkeypatch.setattr(
        f"{SVC}.compra_repository.obtener",
        AsyncMock(side_effect=AssertionError("se leyó la compra sin bloqueo")),
    )
    monkeypatch.setattr(
        f"{SVC}.compra_repository.bloquear", _registra(conn, "bloquear", _compra("P"))
    )
    monkeypatch.setattr(
        f"{SVC}.compra_repository.marcar_cancelada", _registra(conn, "cancelar", _compra("C"))
    )
    monkeypatch.setattr(f"{SVC}._construir_out", AsyncMock(return_value=MagicMock()))

    await compra_service.cancelar(conn, COMPRA_ID)  # type: ignore[arg-type]

    assert conn.eventos == ["BEGIN", "bloquear", "cancelar", "COMMIT"]


async def test_bloquear_compra_usa_for_update_solo_sobre_compras() -> None:
    conn = FakeConn()
    await compra_repository.bloquear(conn, COMPRA_ID)  # type: ignore[arg-type]
    assert conn.sql[0][0].rstrip().endswith("FOR UPDATE OF c")


async def test_marcar_estado_condiciona_el_estado_previo() -> None:
    conn = FakeConn(resultado_execute="UPDATE 0")
    resultado = await compra_repository.marcar_estado(
        conn,  # type: ignore[arg-type]
        COMPRA_ID,
        "R",
        estados_previos=("P", "PARCIAL"),
    )
    assert resultado is None
    sql, args = conn.sql[0]
    assert "estado = ANY($3::text[])" in sql
    assert args[2] == ["P", "PARCIAL"]
