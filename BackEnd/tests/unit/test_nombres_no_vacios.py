"""N-INV1 (prueba E2E v1.2.0): un nombre vacío al editar se guardaba y la
respuesta, que exige min_length=1, fallaba con 500; el listado de insumos de
la sucursal dejaba de cargar. Ningún schema de edición acepta ya un nombre
vacío o solo con espacios, y los válidos llegan sin espacios en los extremos.
"""

from __future__ import annotations

import pytest
from app.schemas.extras import ExtrasUpdate
from app.schemas.horarios_cajas import CajaAdminUpdate, HorarioUpdate
from app.schemas.insumo import InsumoUpdate
from app.schemas.paquetes import PaquetesUpdate
from app.schemas.presentacion_insumo import PresentacionUpdate
from app.schemas.producto import ProductoUpdate
from app.schemas.proveedor import ProveedorUpdate
from app.schemas.tipos_evento import TiposEventoUpdate
from pydantic import BaseModel, ValidationError

SCHEMAS: list[type[BaseModel]] = [
    InsumoUpdate,
    ProveedorUpdate,
    PaquetesUpdate,
    TiposEventoUpdate,
    PresentacionUpdate,
    ExtrasUpdate,
    ProductoUpdate,
    HorarioUpdate,
    CajaAdminUpdate,
]


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda s: s.__name__)
@pytest.mark.parametrize("nombre", ["", "   "])
def test_nombre_vacio_se_rechaza(schema: type[BaseModel], nombre: str) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate({"nombre": nombre})


@pytest.mark.parametrize("schema", SCHEMAS, ids=lambda s: s.__name__)
def test_nombre_valido_se_recorta_y_omitirlo_no_cambia_nada(schema: type[BaseModel]) -> None:
    valido = schema.model_validate({"nombre": "  Servilletas  "}).model_dump()
    assert valido["nombre"] == "Servilletas"
    assert schema.model_validate({}).model_dump()["nombre"] is None
