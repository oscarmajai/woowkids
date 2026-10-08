"""El CSV de indicadores dice de qué sucursal y periodo es, y el del
kardex trae el nombre de quien registró y la hora local de la sucursal."""

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app.schemas.auth import TokenData
from app.services import branch_service, inventario_service


def _token(role: str, sub: str | None = None, branch_id=None) -> TokenData:
    return TokenData(
        sub=sub or str(uuid4()),
        email="admin@test.com",
        role=role,
        branch_id=branch_id,
        permissions=[],
        jti="jti",
        exp=datetime(2099, 1, 1, tzinfo=UTC),
    )


def _sucursal(**overrides):
    base = {
        "id": uuid4(),
        "nombre": "Zapopan Plaza Patria",
        "direccion": None,
        "ciudad": None,
        "estado": None,
        "codigo_postal": None,
        "zona_horaria": "America/Mexico_City",
        "hora_apertura": datetime(2026, 1, 1, 10).time(),
        "hora_cierre": datetime(2026, 1, 1, 21).time(),
        "telefono": None,
        "correo": "plazapatria@woowkids.mx",
        "administrador_id": uuid4(),
        "administrador_name": "Sofía",
        "administrador_email": "admin.zapopan@woowkids.mx",
        "clave": "SUC-ZAP-PP",
        "activo": True,
        "creado": None,
        "creado_por": None,
        "creador_name": None,
        "modificado": None,
        "modificado_por": None,
        "modificador_name": None,
    }
    base.update(overrides)
    return base


def test_sucursal_expone_el_correo_del_administrador_aparte_del_suyo():
    resp = branch_service._to_response(_sucursal())  # type: ignore[arg-type]
    assert resp.administrador_email == "admin.zapopan@woowkids.mx"
    assert resp.correo == "plazapatria@woowkids.mx"


# ── CSV de indicadores con sucursal y periodo ────────────────────────────────


_INDICADORES = {"ventas": Decimal("1500"), "ninos_atendidos": 12, "eventos": 2, "cajas_abiertas": 1}


@pytest.mark.asyncio
async def test_csv_de_indicadores_lleva_sucursal_y_periodo():
    record = _sucursal()
    with (
        patch("app.services.branch_service.get_sucursal_by_id", AsyncMock(return_value=record)),
        patch(
            "app.services.branch_service.get_indicadores_sucursal",
            AsyncMock(return_value=_INDICADORES),
        ),
    ):
        fila, nombre = await branch_service.exportar_indicadores(
            object(),  # type: ignore[arg-type]
            record["id"],
            date(2026, 10, 1),
            date(2026, 10, 31),
            _token("AdministradorSistema"),
        )

    assert fila["sucursal"] == "Zapopan Plaza Patria"
    assert fila["clave"] == "SUC-ZAP-PP"
    assert (fila["desde"], fila["hasta"]) == ("2026-10-01", "2026-10-31")
    assert fila["ventas"] == Decimal("1500")
    assert nombre == "indicadores_SUC-ZAP-PP_2026-10-01_2026-10-31.csv"


@pytest.mark.asyncio
async def test_csv_de_indicadores_sin_clave():
    record = _sucursal(clave=None)
    with (
        patch("app.services.branch_service.get_sucursal_by_id", AsyncMock(return_value=record)),
        patch(
            "app.services.branch_service.get_indicadores_sucursal",
            AsyncMock(return_value=_INDICADORES),
        ),
    ):
        fila, nombre = await branch_service.exportar_indicadores(
            object(),  # type: ignore[arg-type]
            record["id"],
            date(2026, 10, 1),
            date(2026, 10, 31),
            _token("AdministradorSistema"),
        )

    assert fila["clave"] == ""
    assert nombre == "indicadores_sucursal_2026-10-01_2026-10-31.csv"


def test_router_csv_de_indicadores_incluye_columnas_de_sucursal_y_periodo():
    from app.api.routers.branches import _INDICADORES_CSV_CAMPOS

    assert _INDICADORES_CSV_CAMPOS[:4] == ["sucursal", "clave", "desde", "hasta"]


# ── Kardex CSV con nombre de usuario y hora local ────────────────────────────


def _movimiento(**overrides):
    base = {
        "id": uuid4(),
        "sucursal_id": uuid4(),
        "insumo_id": uuid4(),
        "insumo_nombre": "Leche",
        "tipo": "E",
        "cantidad": Decimal("1000"),
        "stock_resultante": Decimal("1000"),
        "motivo": "compra",
        "referencia_id": None,
        "notas": None,
        "costo_total": Decimal("25"),
        "creado": datetime(2026, 10, 3, 7, 24, 33, tzinfo=UTC),
        "creado_por": uuid4(),
        "creado_por_nombre": "Sofía Ramírez",
        "zona_horaria": "America/Mexico_City",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_kardex_csv_usa_nombre_de_usuario_y_hora_local():
    with patch(
        "app.services.inventario_service.movimiento_inventario_repository.listar_por_insumo",
        AsyncMock(return_value=[_movimiento()]),
    ):
        filas = await inventario_service.filas_export_movimientos(object(), uuid4())  # type: ignore[arg-type]

    # 07:24 UTC = 01:24 en Ciudad de México (UTC-6).
    assert filas[0]["creado"] == "2026-10-03 01:24:33"
    assert filas[0]["creado_por"] == "Sofía Ramírez"


@pytest.mark.asyncio
async def test_kardex_csv_sin_usuario_deja_la_celda_vacia():
    with patch(
        "app.services.inventario_service.movimiento_inventario_repository.listar_por_insumo",
        AsyncMock(
            return_value=[
                _movimiento(creado_por=None, creado_por_nombre=None, zona_horaria="America/Tijuana")
            ]
        ),
    ):
        filas = await inventario_service.filas_export_movimientos(object(), uuid4())  # type: ignore[arg-type]

    assert filas[0]["creado"] == "2026-10-03 00:24:33"
    assert filas[0]["creado_por"] == ""
