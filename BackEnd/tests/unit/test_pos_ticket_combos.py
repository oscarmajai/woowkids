"""M12 / M13 / M14 / N10 / M3 / B5 sin BD: enlace de hijos de combo con su
renglón, servicios vendibles en caja, POST /comandas sin movimiento de caja,
datos del ticket en el detalle de la orden y el 409 de idempotencia en curso.

Las pruebas contra PostgreSQL real están en tests/db/test_pos_ticket_combos_pg.py.
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.exceptions import IdempotenciaEnCursoError
from app.models.comanda import DetalleComanda, indices_renglon_padre
from app.schemas.comanda import ComandaModifyRequest, DetalleCreate
from app.schemas.pagos import DetalleOrdenOut
from app.services import comanda_service, precios_venta

COMBO = str(uuid4())
HOTDOG = str(uuid4())
REFRESCO = str(uuid4())
PIZZA = str(uuid4())


def _d(producto: str, cantidad: int = 1, **extra: Any) -> DetalleCreate:
    return DetalleCreate(
        producto_id=producto,
        nombre="x",
        cantidad=cantidad,
        precio_unitario=Decimal("0"),
        subtotal=Decimal("0"),
        **extra,
    )


def _hijo(producto: str, instancia: str | None) -> DetalleCreate:
    return _d(producto, es_hijo_combo=True, es_hijo_de=COMBO, id_combo_padre=instancia)


# ── M13: indices_renglon_padre ───────────────────────────────────────────────


def test_combo_dividido_cada_unidad_va_a_su_renglon() -> None:
    detalles = [
        _d(COMBO),
        _hijo(HOTDOG, "i1"),
        _hijo(REFRESCO, "i1"),
        _d(COMBO),
        _hijo(HOTDOG, "i2"),
        _hijo(REFRESCO, "i2"),
        _d(PIZZA),
    ]
    assert indices_renglon_padre(detalles) == [None, 0, 0, None, 3, 3, None]


def test_dos_combos_en_un_renglon_van_al_mismo_padre() -> None:
    detalles = [_d(COMBO, 2), *(_hijo(p, i) for i in ("a", "b") for p in (HOTDOG, REFRESCO))]
    assert indices_renglon_padre(detalles) == [None, 0, 0, 0, 0]


def test_padres_primero_y_unidades_despues_se_reparten_en_orden() -> None:
    detalles = [
        _d(COMBO, 2),
        _d(COMBO),
        _hijo(HOTDOG, "a"),
        _hijo(HOTDOG, "b"),
        _hijo(HOTDOG, "c"),
    ]
    assert indices_renglon_padre(detalles) == [None, None, 0, 0, 1]


def test_hijo_sin_unidad_va_al_primer_renglon_y_sin_padre_queda_suelto() -> None:
    otro_combo = _d(PIZZA, es_hijo_combo=True, es_hijo_de=str(uuid4()))
    assert indices_renglon_padre([_d(COMBO), _hijo(HOTDOG, None), otro_combo]) == [
        None,
        0,
        None,
    ]


def test_acepta_dicts_de_la_expansion_del_servidor() -> None:
    detalles = [
        {"producto_id": COMBO, "cantidad": 1},
        {"producto_id": HOTDOG, "es_hijo_combo": True, "es_hijo_de": COMBO, "id_combo_padre": "x"},
    ]
    assert indices_renglon_padre(detalles) == [None, 0]


def _detalle_comanda(id_: str, padre: str | None = None) -> DetalleComanda:
    return DetalleComanda(
        id=id_,
        comanda_id="c",
        producto_id="p",
        cantidad=1,
        precio_unitario=Decimal("0"),
        importe=Decimal("0"),
        sucursal_id="s",
        detalle_padre_id=padre,
    )


def test_quitar_un_combo_arrastra_solo_sus_hijos() -> None:
    detalles = [
        _detalle_comanda("c1"),
        _detalle_comanda("h1", "c1"),
        _detalle_comanda("c2"),
        _detalle_comanda("h2", "c2"),
        _detalle_comanda("suelto"),
    ]
    assert comanda_service.ids_con_hijos_de_combo(detalles, ["c2"]) == ["c2", "h2"]
    assert comanda_service.ids_con_hijos_de_combo(detalles, ["h1", "c1"]) == ["h1", "c1"]


# ── M14: servicios en el POS ─────────────────────────────────────────────────


async def test_un_servicio_se_cobra_en_el_pos() -> None:
    sucursal = uuid4()
    servicio = uuid4()
    catalogo = {
        servicio: {
            "nombre": "Pintacaritas",
            "precio_unitario": Decimal("60.00"),
            "tipo": "S",
            "es_combo": False,
            "activo": True,
            "sucursal_id": sucursal,
        }
    }
    detalle = DetalleCreate(
        producto_id=str(servicio),
        nombre="Pintacaritas",
        cantidad=2,
        precio_unitario=Decimal("60.00"),
        subtotal=Decimal("120.00"),
    )
    with patch.object(
        precios_venta.producto_repository, "obtener_para_venta", AsyncMock(return_value=catalogo)
    ):
        venta = await precios_venta.calcular_venta(MagicMock(), sucursal, [detalle])
    assert venta.subtotal == Decimal("120.00")


# ── N10: POST /comandas no registra venta en caja ────────────────────────────


async def test_post_comandas_crea_sin_movimiento_de_caja() -> None:
    comanda_in = SimpleNamespace(
        sucursal_id=uuid4(),
        detalles_comanda=[],
        total_final=Decimal("95"),
        model_copy=lambda update: SimpleNamespace(sucursal_id=uuid4(), **update),
    )
    crear = AsyncMock()
    venta = precios_venta.VentaCalculada(detalles=[], subtotal=Decimal("95"))
    with (
        patch.object(
            comanda_service.precios_venta, "calcular_venta", AsyncMock(return_value=venta)
        ),
        patch.object(comanda_service, "crear_comanda", crear),
    ):
        await comanda_service.crear_comanda_pos(MagicMock(), comanda_in, SimpleNamespace())  # type: ignore[arg-type]
    assert crear.await_args.args[3] is None


# ── M12: el detalle de la orden conserva los datos del ticket ────────────────


def test_detalle_de_orden_devuelve_cliente_cambio_y_sucursal() -> None:
    out = DetalleOrdenOut.model_validate(
        {
            "referencia_id": "r",
            "titulo": "A1",
            "total_final": 170.0,
            "estado_actual": "P",
            "metodos_pago": [],
            "detalles": [
                {
                    "id": "h",
                    "producto_nombre": "Hot dog",
                    "cantidad": 1,
                    "precio_unitario": 0,
                    "importe": 0,
                    "detalle_padre_id": "c",
                }
            ],
            "nombre_cliente": "Mariana",
            "cambio": 30.0,
            "sucursal": {"nombre": "Patria", "direccion": "Av. Patria 1950"},
            "modificado": "2026-10-03T12:00:00+00:00",
        }
    )
    datos = out.model_dump()
    assert datos["nombre_cliente"] == "Mariana"
    assert datos["cambio"] == 30.0
    assert datos["sucursal"]["direccion"] == "Av. Patria 1950"
    assert datos["detalles"][0]["detalle_padre_id"] == "c"
    assert datos["modificado"] == "2026-10-03T12:00:00+00:00"


# ── B5: la versión esperada es opcional ──────────────────────────────────────


def test_editar_orden_acepta_version_opcional() -> None:
    assert ComandaModifyRequest(detalles_ids_a_eliminar=[str(uuid4())]).modificado_esperado is None
    con = ComandaModifyRequest(
        detalles_ids_a_eliminar=[str(uuid4())], modificado_esperado="2026-10-03T12:00:00+00:00"
    )
    assert con.modificado_esperado is not None


async def test_editar_orden_con_version_vieja_no_toca_nada() -> None:
    from datetime import UTC, datetime

    from app.exceptions.comandas import ComandaModificadaError

    modificar = AsyncMock()
    estado = {"modificado": datetime(2026, 10, 3, 12, 5, tzinfo=UTC)}
    with (
        patch.object(
            comanda_service.comanda_repository,
            "get_estado_comanda",
            AsyncMock(return_value=estado),
        ),
        patch.object(comanda_service.comanda_repository, "modificar_comanda_parcial", modificar),
        pytest.raises(ComandaModificadaError),
    ):
        await comanda_service.modificar_comanda_parcial(
            MagicMock(),
            str(uuid4()),
            [str(uuid4())],
            modificado_esperado=datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
        )
    modificar.assert_not_called()


# ── M3: choque de la clave de idempotencia → 409, no 500 ─────────────────────


def test_idempotencia_en_curso_es_409() -> None:
    err = IdempotenciaEnCursoError()
    assert err.status_code == 409
    assert err.detail["code"] == "IDEMPOTENCIA_EN_CURSO"  # type: ignore[index]


async def test_cobro_repetido_espera_el_candado_y_devuelve_la_venta_original() -> None:
    from app.schemas.pagos import PagoCompletoRequest
    from app.services import pago_service

    conn = MagicMock()

    @asynccontextmanager
    async def transaccion() -> Any:
        yield

    conn.transaction = transaccion
    body = PagoCompletoRequest.model_validate(
        {
            "total_final": "95.00",
            "detalles_comanda": [
                {
                    "producto_id": PIZZA,
                    "nombre": "Pizza",
                    "cantidad": 1,
                    "precio_unitario": "95.00",
                    "subtotal": "95.00",
                }
            ],
            "pagos": [{"metodo_pago_id": str(uuid4()), "monto": "95.00"}],
        }
    )
    original = SimpleNamespace(id="orig", detalles=[])
    # Primera revisión (sin candado): todavía no existe; tras el candado, sí.
    idem = AsyncMock(side_effect=[None, original])
    bloquear = AsyncMock()
    venta = precios_venta.VentaCalculada(detalles=[], subtotal=Decimal("95.00"))
    with (
        patch.object(pago_service, "_comanda_idempotente", idem),
        patch.object(pago_service.pago_repository, "bloquear_clave_idempotencia", bloquear),
        patch.object(pago_service, "_validar_metodos_pago", AsyncMock()),
        patch.object(pago_service.precios_venta, "calcular_venta", AsyncMock(return_value=venta)),
        patch.object(
            pago_service.metodos_pago_repository, "obtener_ids_por_tipo", AsyncMock(return_value=[])
        ),
        patch.object(
            pago_service.comanda_repository, "crear_comanda_con_detalles", AsyncMock()
        ) as crear,
    ):
        resultado = await pago_service.completar_pago(
            conn, body, uuid4(), uuid4(), "apertura", idempotency_key="clave-1"
        )
    assert resultado is original
    bloquear.assert_awaited_once_with(conn, "clave-1")
    crear.assert_not_called()
