"""A12 / M23: cálculo y validación de cuánto recibir de cada línea de una compra.
La prueba contra BD real está en tests/db/test_recepcion_compras.py."""

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.exceptions import Conflicto, RecepcionInvalidaError
from app.schemas.compra import LineaRecepcion
from app.services.compra_service import cantidades_a_recibir


def _detalle(nombre: str, cantidad: str, recibida: str = "0") -> dict[str, Any]:
    return {
        "id": uuid4(),
        "insumo_nombre": nombre,
        "cantidad": Decimal(cantidad),
        "cantidad_recibida": Decimal(recibida),
    }


def _linea(detalle_id: UUID, cantidad: str) -> LineaRecepcion:
    return LineaRecepcion(detalle_id=detalle_id, cantidad=Decimal(cantidad))


def test_sin_lineas_recibe_todo_lo_pendiente() -> None:
    a, b, c = _detalle("A", "10"), _detalle("B", "2", "0.5"), _detalle("C", "3", "3")
    assert cantidades_a_recibir([a, b, c], None) == {a["id"]: 10, b["id"]: Decimal("1.5")}


def test_linea_en_cero_o_ausente_no_se_recibe() -> None:
    a, b, c = _detalle("A", "10"), _detalle("B", "10"), _detalle("C", "10")
    resultado = cantidades_a_recibir([a, b, c], [_linea(a["id"], "4"), _linea(b["id"], "0")])
    assert resultado == {a["id"]: 4}


def test_cantidad_mayor_a_lo_pendiente_responde_422_con_la_linea() -> None:
    a = _detalle("Aceite", "10", "7")
    with pytest.raises(RecepcionInvalidaError) as exc:
        cantidades_a_recibir([a], [_linea(a["id"], "3.5")])
    assert exc.value.status_code == 422
    assert exc.value.detail["linea"] == {
        "detalle_id": str(a["id"]),
        "insumo_nombre": "Aceite",
        "solicitado": "3.5",
        "pendiente": "3",
    }
    assert "excede lo pendiente" in exc.value.detail["message"]


def test_cantidad_sobre_una_linea_ya_completa_responde_422() -> None:
    a, b = _detalle("A", "10", "10"), _detalle("B", "10")
    with pytest.raises(RecepcionInvalidaError):
        cantidades_a_recibir([a, b], [_linea(a["id"], "1"), _linea(b["id"], "1")])


def test_detalle_ajeno_o_repetido_responde_422() -> None:
    a = _detalle("A", "10")
    with pytest.raises(RecepcionInvalidaError):
        cantidades_a_recibir([a], [_linea(uuid4(), "1")])
    with pytest.raises(RecepcionInvalidaError):
        cantidades_a_recibir([a], [_linea(a["id"], "1"), _linea(a["id"], "1")])


@pytest.mark.parametrize("lineas", [[], "ceros"])
def test_lista_sin_cantidades_responde_422(lineas: Any) -> None:
    a = _detalle("A", "10")
    if lineas == "ceros":
        lineas = [_linea(a["id"], "0")]
    with pytest.raises(RecepcionInvalidaError):
        cantidades_a_recibir([a], lineas)


def test_compra_sin_pendientes_responde_409() -> None:
    a = _detalle("A", "10", "10")
    with pytest.raises(Conflicto):
        cantidades_a_recibir([a], None)
