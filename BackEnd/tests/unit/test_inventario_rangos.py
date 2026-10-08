"""Límites de cantidades y costos en los schemas de inventario y
compras. Sin límites, `1e12` desbordaba la columna y `0.0004` se redondeaba a 0
y rompía su CHECK: ambos respondían 500. El costo unitario acepta 6 decimales
(numeric(14,6), migración 097). La parte con BD está en
tests/db/test_inventario_rangos_pg.py."""

from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from app.schemas.compra import CompraCrear, DetalleCompraItem, LineaRecepcion
from app.schemas.insumo import InsumoCrear
from app.schemas.movimiento_inventario import ConteoFisicoCreate, MovimientoManualCreate
from app.schemas.presentacion_insumo import PresentacionCrear
from pydantic import ValidationError


def _linea(cantidad: str = "1", costo: str = "1") -> dict[str, Any]:
    return {
        "insumo_id": str(uuid4()),
        "unidad_medida_id": str(uuid4()),
        "cantidad": cantidad,
        "costo_unitario": costo,
    }


@pytest.mark.parametrize("cantidad", ["999999999999", "1e12", "0.0004", "1.2345"])
def test_linea_de_compra_con_cantidad_fuera_de_rango_es_invalida(cantidad: str) -> None:
    with pytest.raises(ValidationError):
        DetalleCompraItem.model_validate(_linea(cantidad=cantidad))


@pytest.mark.parametrize("cantidad", ["10000000000", "0.0004"])
def test_movimiento_manual_con_cantidad_fuera_de_rango_es_invalido(cantidad: str) -> None:
    with pytest.raises(ValidationError):
        MovimientoManualCreate.model_validate({"tipo": "E", "cantidad": cantidad})


@pytest.mark.parametrize(
    ("modelo", "datos"),
    [
        (ConteoFisicoCreate, {"stock_contado": "1e12"}),
        (ConteoFisicoCreate, {"stock_contado": "1.0004"}),
        (PresentacionCrear, {"nombre": "Caja", "equivalencia_base": "1e12"}),
        (PresentacionCrear, {"nombre": "Caja", "equivalencia_base": "0.0004"}),
        (LineaRecepcion, {"detalle_id": str(uuid4()), "cantidad": "1e12"}),
    ],
)
def test_otras_cantidades_de_inventario_fuera_de_rango_son_invalidas(
    modelo: type, datos: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError):
        modelo.model_validate(datos)


def test_alta_de_insumo_con_stock_fuera_de_rango_es_invalida() -> None:
    base = {
        "sucursal_id": str(uuid4()),
        "nombre": "Harina",
        "unidad_base_id": str(uuid4()),
        "unidad_compra_id": str(uuid4()),
    }
    for campo in ("stock_inicial", "stock_minimo", "punto_reorden", "stock_maximo"):
        with pytest.raises(ValidationError):
            InsumoCrear.model_validate({**base, campo: "1e12"})


def test_compra_con_importe_que_no_cabe_en_el_total_es_invalida() -> None:
    with pytest.raises(ValidationError, match="importe de la línea"):
        DetalleCompraItem.model_validate(_linea(cantidad="9999999", costo="9999999"))
    with pytest.raises(ValidationError, match="total de la compra"):
        CompraCrear.model_validate(
            {
                "sucursal_id": str(uuid4()),
                "proveedor_id": str(uuid4()),
                "detalles": [_linea("1000000", "60"), _linea("1000000", "60")],
            }
        )
    with pytest.raises(ValidationError):
        CompraCrear.model_validate(
            {
                "sucursal_id": str(uuid4()),
                "proveedor_id": str(uuid4()),
                "iva": "1.005",
                "detalles": [_linea()],
            }
        )


def test_cantidades_validas_siguen_pasando() -> None:
    linea = DetalleCompraItem.model_validate(_linea(cantidad="9999999.999", costo="0.5"))
    assert linea.cantidad == Decimal("9999999.999")
    assert MovimientoManualCreate.model_validate({"tipo": "M", "cantidad": "0.001"}).cantidad == (
        Decimal("0.001")
    )


def test_costo_unitario_acepta_seis_decimales_y_no_mas() -> None:
    assert DetalleCompraItem.model_validate(_linea(costo="0.123456")).costo_unitario == Decimal(
        "0.123456"
    )
    with pytest.raises(ValidationError):
        DetalleCompraItem.model_validate(_linea(costo="0.1234567"))
