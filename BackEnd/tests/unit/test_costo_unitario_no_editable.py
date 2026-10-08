"""El costo unitario del insumo es el promedio PEPS de sus capas y se
recalcula en cada movimiento; un valor editado a mano se perdía en silencio en
el siguiente, así que la edición lo rechaza con 422 COSTO_NO_EDITABLE."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.exceptions.inventario import CostoNoEditableError
from app.schemas.auth import TokenData
from app.schemas.insumo import InsumoOut, InsumoUpdate
from app.services import insumo_service


def _token() -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="inv@test.local",
        role="3",
        branch_id=uuid4(),
        jti="x",
        exp=datetime.now(UTC) + timedelta(hours=1),
    )


def _insumo_out() -> InsumoOut:
    return InsumoOut(
        id=uuid4(),
        sucursal_id=uuid4(),
        nombre="Aceite",
        unidad_base_id=uuid4(),
        unidad_compra_id=uuid4(),
        stock_actual=Decimal("10"),
        stock_minimo=Decimal("0"),
        costo_unitario=Decimal("0.042692"),
        activo=True,
        creado=None,
        creado_por=None,
        modificado=None,
        modificado_por=None,
    )


@pytest.mark.parametrize("costo", ["0.50", None])
async def test_editar_el_costo_unitario_a_mano_responde_422(
    monkeypatch: pytest.MonkeyPatch, costo: str | None
) -> None:
    actualizar = AsyncMock()
    monkeypatch.setattr(insumo_service, "obtener", AsyncMock(return_value=_insumo_out()))
    monkeypatch.setattr(insumo_service.insumo_repository, "actualizar", actualizar)

    with pytest.raises(CostoNoEditableError) as exc:
        await insumo_service.actualizar(
            MagicMock(),
            uuid4(),
            InsumoUpdate.model_validate({"nombre": "Aceite", "costo_unitario": costo}),
            _token(),
        )

    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "COSTO_NO_EDITABLE"
    actualizar.assert_not_called()


async def test_editar_sin_costo_unitario_sigue_funcionando(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insumo = _insumo_out()
    actualizar = AsyncMock(return_value=insumo.model_dump())
    monkeypatch.setattr(insumo_service, "obtener", AsyncMock(return_value=insumo))
    monkeypatch.setattr(insumo_service.insumo_repository, "actualizar", actualizar)

    await insumo_service.actualizar(
        MagicMock(), insumo.id, InsumoUpdate(nombre="Aceite de oliva"), _token()
    )

    assert "costo_unitario" not in actualizar.call_args.args[2]
