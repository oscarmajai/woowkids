"""C1 — Aislamiento por sucursal en la API (pruebas E2E 2026-10-03).

Barrido parametrizado de endpoints: un usuario de la sucursal B (rol con
sucursal fija) pide datos de la sucursal A.

- Listados/reportes/altas con ``sucursal_id`` de A → 403.
- Recursos por id que pertenecen a A → 404 (no se revela que existen).

La BD no se toca: ``alcance_repository.sucursal_de`` se simula para que todo
recurso "sea" de la sucursal A, y la conexión es un objeto vacío, de modo que
si un endpoint llegara al service (es decir, si no aplicara el aislamiento)
reventaría con 500 y el test fallaría.

Para agregar un endpoint basta con sumarlo a ``CASOS_403`` o ``CASOS_404``.
Los casos positivos (misma sucursal) viven en el test de integración
``tests/integration/test_aislamiento_sucursal_db.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.api.deps import apertura_operando_id, get_current_user, requiere_turno_abierto
from app.core.database import get_db
from app.core.scope import (
    asegurar_misma_sucursal,
    resolver_sucursal,
    resolver_sucursal_obligatoria,
)
from app.main import app
from app.repositories import alcance_repository
from app.schemas.auth import TokenData
from app.services import permission_service
from fastapi import HTTPException
from fastapi.testclient import TestClient

SUC_A = UUID("aaaaaaaa-0000-0000-0000-00000000000a")  # dueña de los datos
SUC_B = UUID("bbbbbbbb-0000-0000-0000-00000000000b")  # sesión del usuario
RID = "cccccccc-0000-0000-0000-00000000000c"  # id de cualquier recurso de A
RID2 = "dddddddd-0000-0000-0000-00000000000d"


def _usuario(rol: str = "Administrador", branch_id: UUID | None = SUC_B) -> TokenData:
    return TokenData(
        sub=str(uuid4()),
        email="admin.b@woowkids.test",
        role=rol,
        branch_id=branch_id,
        permissions=[],
        jti=str(uuid4()),
        exp=datetime.now(tz=UTC) + timedelta(hours=1),
    )


# ── Reglas puras de app/core/scope.py ───────────────────────────────────────


def test_rol_fijo_sin_parametro_usa_su_sucursal() -> None:
    assert resolver_sucursal(_usuario(), None) == SUC_B


def test_rol_fijo_con_su_propia_sucursal_pasa() -> None:
    assert resolver_sucursal(_usuario("Cajero"), str(SUC_B)) == SUC_B


def test_rol_fijo_con_otra_sucursal_da_403() -> None:
    with pytest.raises(HTTPException) as exc:
        resolver_sucursal(_usuario("Cocina"), SUC_A)
    assert exc.value.status_code == 403


def test_rol_fijo_sin_sucursal_en_sesion_da_403() -> None:
    with pytest.raises(HTTPException) as exc:
        resolver_sucursal(_usuario(branch_id=None), None)
    assert exc.value.status_code == 403


def test_sistema_sin_parametro_ni_selector_ve_todas() -> None:
    assert resolver_sucursal(_usuario("AdministradorSistema", None), None) is None


def test_sistema_usa_selector_o_parametro() -> None:
    sistema_en_b = _usuario("AdministradorSistema", SUC_B)
    assert resolver_sucursal(sistema_en_b, None) == SUC_B
    assert resolver_sucursal(sistema_en_b, SUC_A) == SUC_A


def test_obligatoria_sin_sucursal_para_sistema_da_422() -> None:
    with pytest.raises(HTTPException) as exc:
        resolver_sucursal_obligatoria(_usuario("AdministradorSistema", None), None)
    assert exc.value.status_code == 422


def test_recurso_de_otra_sucursal_da_404_y_sistema_pasa() -> None:
    with pytest.raises(HTTPException) as exc:
        asegurar_misma_sucursal(_usuario("Rol personalizado"), SUC_A, "Insumo")
    assert exc.value.status_code == 404
    asegurar_misma_sucursal(_usuario("AdministradorSistema", None), SUC_A, "Insumo")
    asegurar_misma_sucursal(_usuario(), SUC_B, "Insumo")


# ── Barrido de endpoints ────────────────────────────────────────────────────


class _ConexionQueNoSeDebeUsar:
    """Si un endpoint llega a consultar la BD sin pasar por el aislamiento,
    cualquier atributo revienta (→ 500) y el test falla."""

    def __getattr__(self, nombre: str) -> Any:
        raise AssertionError(f"El endpoint usó la conexión ({nombre}) sin validar la sucursal")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    usuario = _usuario()
    codigos = {
        codigo
        for ruta in app.routes
        for dep in getattr(getattr(ruta, "dependant", None), "dependencies", [])
        for codigo in _codigos_permiso(dep)
    }
    monkeypatch.setitem(permission_service._cache, "Administrador", frozenset(codigos))

    async def _sucursal_de(_conn: Any, _tipo: str, _rid: UUID) -> UUID:
        return SUC_A

    monkeypatch.setattr(alcance_repository, "sucursal_de", _sucursal_de)

    app.dependency_overrides[get_current_user] = lambda: usuario
    app.dependency_overrides[get_db] = lambda: _ConexionQueNoSeDebeUsar()
    app.dependency_overrides[apertura_operando_id] = lambda: str(uuid4())
    app.dependency_overrides[requiere_turno_abierto] = lambda: usuario
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def _codigos_permiso(dep: Any) -> list[str]:
    """Todos los códigos de permiso usados por require_permission, para darle
    al rol de prueba acceso a todo y aislar la validación de sucursal."""
    call = getattr(dep, "call", None)
    cierre = getattr(call, "__closure__", None) or ()
    codigos: list[str] = []
    for celda in cierre:
        valor = celda.cell_contents
        if isinstance(valor, tuple) and all(isinstance(v, str) and ":" in v for v in valor):
            codigos.extend(valor)
    for sub in getattr(dep, "dependencies", []):
        codigos.extend(_codigos_permiso(sub))
    return codigos


A = str(SUC_A)
B = str(SUC_B)

_DETALLE_COMPRA = [
    {"insumo_id": RID2, "unidad_medida_id": RID2, "cantidad": 1, "costo_unitario": 1}
]


def _reservacion(sucursal_id: str) -> dict[str, Any]:
    return {
        "sucursal_id": sucursal_id,
        "tipo_evento_id": RID2,
        "paquete_id": RID2,
        "nombre_cliente": "Cliente",
        "telefono_cliente": "3312345678",
        "fecha_evento": "2026-10-10",
        "hora_inicio": "16:00:00",
        "hora_fin": "19:00:00",
        "numero_personas": 10,
        "precio_base": 1000,
        "precio_total": 1000,
    }


# (método, ruta, kwargs de la petición)
CASOS_403: list[tuple[str, str, dict[str, Any]]] = [
    # Inventario
    ("GET", f"/api/insumos?sucursal_id={A}", {}),
    ("GET", f"/api/insumos/alertas?sucursal_id={A}", {}),
    ("GET", f"/api/insumos/reporte-cogs?sucursal_id={A}", {}),
    ("GET", f"/api/insumos/reporte-cogs/resumen?sucursal_id={A}", {}),
    ("GET", f"/api/insumos/reporte-cogs/export?sucursal_id={A}", {}),
    ("GET", f"/api/insumos/export?sucursal_id={A}", {}),
    ("GET", f"/api/insumos/estimaciones?sucursal_id={A}", {}),
    (
        "POST",
        "/api/insumos",
        {
            "json": {
                "sucursal_id": A,
                "nombre": "Leche",
                "unidad_base_id": RID2,
                "unidad_compra_id": RID2,
            }
        },
    ),
    ("GET", f"/api/proveedores?sucursal_id={A}", {}),
    ("POST", "/api/proveedores", {"json": {"sucursal_id": A, "nombre": "Proveedor A"}}),
    ("GET", f"/api/compras?sucursal_id={A}", {}),
    (
        "POST",
        "/api/compras",
        {"json": {"sucursal_id": A, "proveedor_id": RID2, "detalles": _DETALLE_COMPRA}},
    ),
    # Reservaciones
    ("GET", f"/api/reservaciones/disponibilidad?sucursal_id={A}&fecha=2026-10-10", {}),
    ("GET", f"/api/reservaciones/evento-cercano/{A}", {}),
    ("POST", "/api/reservaciones", {"json": _reservacion(A)}),
    ("POST", "/api/reservaciones/completa", {"json": {"reservacion": _reservacion(A)}}),
]

CASOS_404: list[tuple[str, str, dict[str, Any]]] = [
    # Inventario
    ("GET", f"/api/insumos/{RID}", {}),
    ("PATCH", f"/api/insumos/{RID}", {"json": {"nombre": "x"}}),
    ("DELETE", f"/api/insumos/{RID}", {}),
    ("GET", f"/api/insumos/{RID}/movimientos", {}),
    ("GET", f"/api/insumos/{RID}/movimientos/export", {}),
    (
        "POST",
        f"/api/insumos/{RID}/movimientos",
        {"json": {"tipo": "M", "cantidad": 1}},
    ),
    ("POST", f"/api/insumos/{RID}/conteo", {"json": {"stock_contado": 1}}),
    ("GET", f"/api/insumos/{RID}/presentaciones", {}),
    (
        "POST",
        f"/api/insumos/{RID}/presentaciones",
        {"json": {"nombre": "Caja", "equivalencia_base": 12}},
    ),
    ("PATCH", f"/api/insumos/{RID}/presentaciones/{RID2}", {"json": {"nombre": "x"}}),
    ("DELETE", f"/api/insumos/{RID}/presentaciones/{RID2}", {}),
    ("GET", f"/api/proveedores/{RID}", {}),
    ("PATCH", f"/api/proveedores/{RID}", {"json": {"nombre": "x"}}),
    ("DELETE", f"/api/proveedores/{RID}", {}),
    ("GET", f"/api/compras/{RID}", {}),
    ("PATCH", f"/api/compras/{RID}", {"json": {"notas": "x"}}),
    (
        "PUT",
        f"/api/compras/{RID}",
        {"json": {"proveedor_id": RID2, "detalles": _DETALLE_COMPRA}},
    ),
    ("POST", f"/api/compras/{RID}/recibir", {}),
    ("POST", f"/api/compras/{RID}/cancelar", {}),
    # Reservaciones (datos personales del cliente)
    ("GET", f"/api/reservaciones/{RID}", {}),
    ("PATCH", f"/api/reservaciones/{RID}", {"json": {"estado": "cancelada"}}),
    ("DELETE", f"/api/reservaciones/{RID}", {}),
    # Alta en mi sucursal pero con paquete/tipo de evento de otra.
    ("POST", "/api/reservaciones", {"json": _reservacion(B)}),
    ("POST", "/api/reservaciones/completa", {"json": {"reservacion": _reservacion(B)}}),
    ("GET", f"/api/reservacion-extras/reservacion/{RID}", {}),
    ("GET", f"/api/reservacion-extras/{RID}", {}),
    (
        "POST",
        "/api/reservacion-extras",
        {"json": {"reservacion_id": RID, "extra_id": RID2, "cantidad": 1, "precio_unitario": 1}},
    ),
    ("PATCH", f"/api/reservacion-extras/{RID}", {"json": {"cantidad": 2}}),
    ("DELETE", f"/api/reservacion-extras/{RID}", {}),
    ("GET", f"/api/reservacion-productos/reservacion/{RID}", {}),
    ("GET", f"/api/reservacion-productos/{RID}", {}),
    (
        "POST",
        "/api/reservacion-productos",
        {
            "json": {
                "reservacion_id": RID,
                "producto_id": RID2,
                "cantidad": 1,
                "precio_unitario": 1,
            }
        },
    ),
    ("PATCH", f"/api/reservacion-productos/{RID}", {"json": {"cantidad": 2}}),
    ("DELETE", f"/api/reservacion-productos/{RID}", {}),
    ("GET", f"/api/pagos-reservacion/reservacion/{RID}", {}),
    ("GET", f"/api/pagos-reservacion/{RID}", {}),
    (
        "POST",
        "/api/pagos-reservacion",
        {"json": {"reservacion_id": RID, "metodo_pago_id": RID2, "monto": 100}},
    ),
    (
        "POST",
        "/api/pagos-reservacion/completar",
        {"json": {"reservacion_id": RID, "pagos": [{"metodo_pago_id": RID2, "monto": 100}]}},
    ),
    ("PATCH", f"/api/pagos-reservacion/{RID}", {"json": {"notas": "x"}}),
    ("DELETE", f"/api/pagos-reservacion/{RID}", {}),
]


def _ids(casos: list[tuple[str, str, dict[str, Any]]]) -> list[str]:
    return [f"{m} {r.split('?')[0]}" for m, r, _ in casos]


def _enviar(client: TestClient, metodo: str, ruta: str, kwargs: dict[str, Any]) -> Any:
    if "form" in kwargs:
        return client.request(
            metodo, ruta, data={"payload": json.dumps(kwargs["form"])}, files=kwargs.get("files")
        )
    return client.request(metodo, ruta, **kwargs)


@pytest.mark.parametrize(("metodo", "ruta", "kwargs"), CASOS_403, ids=_ids(CASOS_403))
def test_otra_sucursal_por_parametro_da_403(
    client: TestClient, metodo: str, ruta: str, kwargs: dict[str, Any]
) -> None:
    resp = _enviar(client, metodo, ruta, kwargs)
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize(("metodo", "ruta", "kwargs"), CASOS_404, ids=_ids(CASOS_404))
def test_recurso_de_otra_sucursal_da_404(
    client: TestClient, metodo: str, ruta: str, kwargs: dict[str, Any]
) -> None:
    resp = _enviar(client, metodo, ruta, kwargs)
    assert resp.status_code == 404, resp.text
