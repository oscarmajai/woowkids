"""C2 / M3 / M11: el cobro del POS (POST /pagos/completar) usa los precios del
catálogo de la sucursal de la sesión, no los del navegador.

Sin BD: los repositorios se simulan con un catálogo en memoria. La prueba
contra PostgreSQL real está en tests/integration/test_precios_servidor_pos_pg.py.
"""

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from app.core import ws_manager
from app.exceptions import PedidoInvalidoError, PrecioCambiadoError, ProductoNoDisponibleError
from app.models.comanda import Comanda
from app.schemas.pagos import PagoCompletoRequest
from app.services import comanda_service, pago_service, precios_venta
from fastapi import status
from pydantic import ValidationError

SUCURSAL = uuid4()
OTRA_SUCURSAL = uuid4()
EFECTIVO = uuid4()
TARJETA = uuid4()

PIZZA = uuid4()
AGUA = uuid4()
COMBO = uuid4()
HOTDOG = uuid4()
REFRESCO = uuid4()
INACTIVO = uuid4()
AJENO = uuid4()
ESTANCIA = uuid4()


def _producto(nombre: str, precio: str, tipo: str = "A", **extra: Any) -> dict[str, Any]:
    return {
        "nombre": nombre,
        "precio_unitario": Decimal(precio),
        "tipo": tipo,
        "es_combo": extra.get("es_combo", False),
        "activo": extra.get("activo", True),
        "sucursal_id": extra.get("sucursal_id", SUCURSAL),
    }


CATALOGO: dict[UUID, dict[str, Any]] = {
    PIZZA: _producto("Pizza individual", "95.00"),
    AGUA: _producto("Agua embotellada", "22.00", "B"),
    COMBO: _producto("Combo Hot dog + Refresco", "120.00", "C", es_combo=True),
    HOTDOG: _producto("Hot dog", "70.00"),
    REFRESCO: _producto("Refresco", "30.00", "B"),
    INACTIVO: _producto("Taller de slime", "50.00", activo=False),
    AJENO: _producto("Pizza de Andares", "10.00", sucursal_id=OTRA_SUCURSAL),
    ESTANCIA: _producto("Hora estancia", "50.00", "E"),
}
DEFINICIONES = {COMBO: {HOTDOG: 1, REFRESCO: 1}}
METODOS = {
    EFECTIVO: {"nombre": "Efectivo", "activo": True, "requiere_referencia": False},
    TARJETA: {"nombre": "Tarjeta", "activo": True, "requiere_referencia": True},
}


def _renglon(producto_id: UUID, precio: str, cantidad: int = 1, **extra: Any) -> dict[str, Any]:
    return {
        "producto_id": str(producto_id),
        "nombre": "lo que diga el navegador",
        "cantidad": cantidad,
        "precio_unitario": precio,
        "subtotal": extra.pop("subtotal", str(Decimal(precio) * cantidad)),
        **extra,
    }


def _hijo(producto_id: UUID, instancia: str, combo: UUID = COMBO, **extra: Any) -> dict[str, Any]:
    return _renglon(
        producto_id,
        extra.pop("precio", "0"),
        extra.pop("cantidad", 1),
        es_hijo_combo=True,
        es_hijo_de=str(combo),
        id_combo_padre=instancia,
        **extra,
    )


def _request(detalles: list[dict[str, Any]], total: str, **extra: Any) -> PagoCompletoRequest:
    pagos = extra.pop("pagos", [{"metodo_pago_id": str(EFECTIVO), "monto": total}])
    return PagoCompletoRequest.model_validate(
        {"total_final": total, "detalles_comanda": detalles, "pagos": pagos, **extra}
    )


@pytest.fixture
def mundo(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Catálogo y colaboradores simulados; devuelve los mocks de escritura
    para poder afirmar que, ante un rechazo, no se escribió nada."""

    async def obtener_para_venta(_conn: Any, ids: list[UUID]) -> dict[UUID, dict[str, Any]]:
        return {i: {"id": i, **CATALOGO[i]} for i in ids if i in CATALOGO}

    async def obtener_definiciones_combo(_conn: Any, ids: list[UUID]) -> dict[UUID, Any]:
        return {i: DEFINICIONES[i] for i in ids if i in DEFINICIONES}

    async def obtener_metodo(_conn: Any, metodo_id: UUID, _sucursal: UUID) -> Any:
        return METODOS.get(metodo_id)

    repo = precios_venta.producto_repository
    monkeypatch.setattr(repo, "obtener_para_venta", obtener_para_venta)
    monkeypatch.setattr(repo, "obtener_definiciones_combo", obtener_definiciones_combo)
    mp_repo = pago_service.metodos_pago_repository
    monkeypatch.setattr(mp_repo, "obtener", obtener_metodo)
    monkeypatch.setattr(mp_repo, "obtener_ids_por_tipo", AsyncMock(return_value={EFECTIVO}))
    monkeypatch.setattr(
        pago_service.lealtad_service.lealtad_repository,
        "obtener_configuracion",
        AsyncMock(return_value={"valor_punto": Decimal("1.00"), "minimo_canje": 50}),
    )
    monkeypatch.setattr(
        pago_service.folio_repository, "siguiente_folio", AsyncMock(return_value="A1")
    )

    async def crear_comanda(_conn: Any, comanda_in: Any, *_args: Any) -> Comanda:
        return Comanda(
            id=str(uuid4()),
            ticket_numero=comanda_in.ticket_numero,
            estado_actual="P",
            total_final=comanda_in.total_final,
            sucursal_id=str(SUCURSAL),
            fecha_hora=None,  # type: ignore[arg-type]
            detalles=[],
        )

    mocks = {
        "crear_comanda": AsyncMock(side_effect=crear_comanda),
        "descontar": AsyncMock(),
        "crear_pagos": AsyncMock(return_value=[]),
        "movimiento": AsyncMock(),
        "cambio": AsyncMock(),
        "redimir": AsyncMock(return_value=Decimal("60.00")),
        "otorgar": AsyncMock(),
    }
    monkeypatch.setattr(
        pago_service.comanda_repository, "crear_comanda_con_detalles", mocks["crear_comanda"]
    )
    monkeypatch.setattr(pago_service.inventario_service, "descontar_por_venta", mocks["descontar"])
    monkeypatch.setattr(pago_service.pago_repository, "crear_pagos", mocks["crear_pagos"])
    monkeypatch.setattr(pago_service, "registrar_movimiento_caja", mocks["movimiento"])
    monkeypatch.setattr(pago_service, "registrar_cambio_caja", mocks["cambio"])
    monkeypatch.setattr(pago_service.lealtad_service, "redimir_puntos", mocks["redimir"])
    monkeypatch.setattr(pago_service.lealtad_service, "otorgar_puntos", mocks["otorgar"])
    monkeypatch.setattr(
        comanda_service, "expandir_detalles_comanda", AsyncMock(side_effect=lambda _c, d: d)
    )
    monkeypatch.setattr(ws_manager.manager, "broadcast", AsyncMock())
    monkeypatch.setattr(pago_service, "asdict", lambda _c: {}, raising=False)
    return mocks


def _conn() -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def transaccion() -> Any:
        yield

    conn.transaction = transaccion
    return conn


async def _cobrar(body: PagoCompletoRequest) -> Comanda:
    return await pago_service.completar_pago(_conn(), body, uuid4(), SUCURSAL, str(uuid4()))


def _nada_escrito(mocks: dict[str, Any]) -> bool:
    return not any(m.await_count for m in mocks.values())


# --- precio manipulado -> 409 sin cobrar -------------------------------------


async def test_precio_unitario_manipulado_da_409_y_no_cobra(mundo: dict[str, Any]) -> None:
    body = _request([_renglon(PIZZA, "1.00")], "1.00")
    with pytest.raises(PrecioCambiadoError) as exc:
        await _cobrar(body)
    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert exc.value.detail["code"] == "PRECIO_CAMBIADO"
    assert exc.value.detail["message"] == (
        "El precio de «Pizza individual» cambió a $95.00. Actualiza el pedido."
    )
    assert _nada_escrito(mundo)


async def test_subtotal_manipulado_con_precio_correcto_da_409(mundo: dict[str, Any]) -> None:
    body = _request([_renglon(PIZZA, "95.00", 2, subtotal="95.00")], "95.00")
    with pytest.raises(PrecioCambiadoError) as exc:
        await _cobrar(body)
    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert _nada_escrito(mundo)


async def test_total_manipulado_con_renglones_correctos_da_409(mundo: dict[str, Any]) -> None:
    body = _request([_renglon(AGUA, "22.00")], "1.00")
    with pytest.raises(PrecioCambiadoError) as exc:
        await _cobrar(body)
    assert exc.value.detail["code"] == "TOTAL_NO_COINCIDE"
    assert "$22.00" in exc.value.detail["message"]
    assert _nada_escrito(mundo)


# --- precio correcto -> se cobra con los precios del catálogo ---------------


async def test_precio_correcto_cobra_con_el_catalogo(mundo: dict[str, Any]) -> None:
    body = _request(
        [_renglon(PIZZA, "95.00", 2), _renglon(AGUA, "22")],
        "212.00",
        pagos=[{"metodo_pago_id": str(EFECTIVO), "monto": "250.00"}],
        cambio="38.00",
    )
    comanda = await _cobrar(body)

    assert comanda.total_final == Decimal("212.00")
    comanda_in = mundo["crear_comanda"].await_args.args[1]
    assert comanda_in.total_final == Decimal("212.00")
    assert [(d.nombre, d.precio_unitario, d.subtotal) for d in comanda_in.detalles_comanda] == [
        ("Pizza individual", Decimal("95.00"), Decimal("190.00")),
        ("Agua embotellada", Decimal("22.00"), Decimal("22.00")),
    ]
    mundo["cambio"].assert_awaited_once()


# --- producto inactivo / de otra sucursal / no vendible ---------------------


async def test_producto_inactivo_da_409(mundo: dict[str, Any]) -> None:
    with pytest.raises(ProductoNoDisponibleError) as exc:
        await _cobrar(_request([_renglon(INACTIVO, "50.00")], "50.00"))
    assert exc.value.status_code == status.HTTP_409_CONFLICT
    assert "«Taller de slime» ya no está disponible" in exc.value.detail["message"]
    assert _nada_escrito(mundo)


@pytest.mark.parametrize("producto", [AJENO, uuid4()], ids=["otra_sucursal", "inexistente"])
async def test_producto_de_otra_sucursal_o_inexistente_da_422(
    mundo: dict[str, Any], producto: UUID
) -> None:
    with pytest.raises(PedidoInvalidoError) as exc:
        await _cobrar(_request([_renglon(producto, "10.00")], "10.00"))
    assert exc.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert exc.value.detail["code"] == "PRODUCTO_INVALIDO"
    assert _nada_escrito(mundo)


async def test_producto_de_estancia_no_se_vende_en_el_pos(mundo: dict[str, Any]) -> None:
    with pytest.raises(PedidoInvalidoError):
        await _cobrar(_request([_renglon(ESTANCIA, "50.00")], "50.00"))


# --- combos ------------------------------------------------------------------


async def test_combo_con_sus_hijos_cobra_solo_el_precio_del_combo(
    mundo: dict[str, Any],
) -> None:
    i1, i2 = str(uuid4()), str(uuid4())
    body = _request(
        [
            _renglon(COMBO, "120.00", 2),
            _hijo(HOTDOG, i1),
            _hijo(REFRESCO, i1, notas_especiales="Sin hielo"),
            _hijo(HOTDOG, i2),
            _hijo(REFRESCO, i2),
        ],
        "240.00",
    )
    await _cobrar(body)
    detalles = mundo["crear_comanda"].await_args.args[1].detalles_comanda
    assert [d.subtotal for d in detalles] == [Decimal("240.00")] + [Decimal("0")] * 4
    hijos = detalles[1:]
    assert all(h.es_hijo_combo and h.es_hijo_de == str(COMBO) for h in hijos)
    assert {h.nombre_combo_padre for h in hijos} == {"Combo Hot dog + Refresco"}
    assert hijos[1].notas_especiales == "Sin hielo"


async def test_combo_sin_hijos_se_acepta(mundo: dict[str, Any]) -> None:
    await _cobrar(_request([_renglon(COMBO, "120.00")], "120.00"))


async def test_precio_de_un_hijo_no_altera_el_total(mundo: dict[str, Any]) -> None:
    """Un hijo con precio inflado no cambia lo cobrado: se guarda a $0 y el
    total sigue siendo el del combo."""
    i1 = str(uuid4())
    body = _request(
        [_renglon(COMBO, "120.00"), _hijo(HOTDOG, i1, precio="500"), _hijo(REFRESCO, i1)],
        "120.00",
    )
    await _cobrar(body)
    detalles = mundo["crear_comanda"].await_args.args[1].detalles_comanda
    assert detalles[1].precio_unitario == Decimal("0")
    assert mundo["crear_comanda"].await_args.args[1].total_final == Decimal("120.00")


@pytest.mark.parametrize(
    "hijos",
    [
        # Un producto ajeno al combo, gratis, colado como "hijo".
        lambda i: [_hijo(HOTDOG, i), _hijo(REFRESCO, i), _hijo(PIZZA, i)],
        # Falta un integrante.
        lambda i: [_hijo(HOTDOG, i)],
        # Cantidad distinta a la definición.
        lambda i: [_hijo(HOTDOG, i, cantidad=3), _hijo(REFRESCO, i)],
        # Hijo de un combo que no está en el pedido.
        lambda i: [_hijo(PIZZA, i, combo=uuid4())],
        # Dos juegos de hijos para un solo combo.
        lambda i: [
            _hijo(HOTDOG, i),
            _hijo(REFRESCO, i),
            _hijo(HOTDOG, str(uuid4())),
            _hijo(REFRESCO, str(uuid4())),
        ],
        # Hijo sin instancia de combo.
        lambda i: [_hijo(HOTDOG, ""), _hijo(REFRESCO, i)],
    ],
    ids=["producto_ajeno", "falta_integrante", "cantidad", "combo_ausente", "de_mas", "sin_id"],
)
async def test_combo_con_hijos_que_no_son_su_definicion_da_422(
    mundo: dict[str, Any], hijos: Any
) -> None:
    body = _request([_renglon(COMBO, "120.00"), *hijos(str(uuid4()))], "120.00")
    with pytest.raises(PedidoInvalidoError) as exc:
        await _cobrar(body)
    assert exc.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert _nada_escrito(mundo)


# --- cantidades (M3) ---------------------------------------------------------


@pytest.mark.parametrize("cantidad", [0, -1, 1000])
def test_cantidad_fuera_de_rango_es_error_de_validacion_422(cantidad: int) -> None:
    """FastAPI convierte este ValidationError del body en 422 (antes: 500)."""
    with pytest.raises(ValidationError):
        _request([_renglon(PIZZA, "95.00", cantidad)], "95.00")


def test_pedido_vacio_es_error_de_validacion() -> None:
    with pytest.raises(ValidationError):
        _request([], "95.00")


async def test_calcular_venta_rechaza_cantidad_cero_aunque_no_pase_por_el_schema() -> None:
    from app.schemas.comanda import DetalleCreate

    detalle = DetalleCreate.model_validate(_renglon(PIZZA, "95.00", 0))
    with pytest.raises(PedidoInvalidoError) as exc:
        await precios_venta.calcular_venta(_conn(), SUCURSAL, [detalle])
    assert exc.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# --- tarjeta sin referencia (M11) --------------------------------------------


@pytest.mark.parametrize("notas", ["", "   ", "CREDITO - Folio: "])
async def test_tarjeta_sin_referencia_da_422(mundo: dict[str, Any], notas: str) -> None:
    body = _request(
        [_renglon(PIZZA, "95.00")],
        "95.00",
        pagos=[{"metodo_pago_id": str(TARJETA), "monto": "95.00", "notas_pago": notas}],
    )
    with pytest.raises(PedidoInvalidoError) as exc:
        await _cobrar(body)
    assert exc.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert exc.value.detail["code"] == "REFERENCIA_REQUERIDA"
    assert _nada_escrito(mundo)


async def test_tarjeta_con_referencia_se_cobra(mundo: dict[str, Any]) -> None:
    body = _request(
        [_renglon(PIZZA, "95.00")],
        "95.00",
        pagos=[
            {
                "metodo_pago_id": str(TARJETA),
                "monto": "95.00",
                "notas_pago": "CREDITO - Folio: 123456",
            }
        ],
    )
    await _cobrar(body)
    mundo["crear_pagos"].assert_awaited_once()


async def test_metodo_de_pago_inexistente_da_422(mundo: dict[str, Any]) -> None:
    body = _request(
        [_renglon(PIZZA, "95.00")], "95.00", pagos=[{"metodo_pago_id": str(uuid4()), "monto": 95}]
    )
    with pytest.raises(PedidoInvalidoError):
        await _cobrar(body)


# --- pagos deben cuadrar exactamente -----------------------------------------


async def test_pago_de_mas_sin_cambio_declarado_se_rechaza(mundo: dict[str, Any]) -> None:
    body = _request(
        [_renglon(PIZZA, "95.00")],
        "95.00",
        pagos=[{"metodo_pago_id": str(EFECTIVO), "monto": "100.00"}],
    )
    with pytest.raises(pago_service.DatosInvalidos):
        await _cobrar(body)
    assert _nada_escrito(mundo)


# --- descuento por puntos ----------------------------------------------------


async def test_descuento_por_puntos_sigue_funcionando(mundo: dict[str, Any]) -> None:
    # 2 pizzas = $190, 60 puntos x $1.00 = $60 de descuento -> $130.
    body = _request(
        [_renglon(PIZZA, "95.00", 2)],
        "130.00",
        celular_cliente="3312345678",
        puntos_a_redimir=60,
    )
    comanda = await _cobrar(body)
    assert comanda.total_final == Decimal("130.00")
    mundo["redimir"].assert_awaited_once()
    # Los puntos ganados se calculan sobre el total neto calculado en el servidor.
    assert mundo["otorgar"].await_args.args[3] == Decimal("130.00")


async def test_descuento_por_puntos_con_total_del_cliente_sin_descontar_da_409(
    mundo: dict[str, Any],
) -> None:
    body = _request(
        [_renglon(PIZZA, "95.00", 2)],
        "100.00",
        celular_cliente="3312345678",
        puntos_a_redimir=60,
    )
    with pytest.raises(PrecioCambiadoError) as exc:
        await _cobrar(body)
    assert exc.value.detail["code"] == "TOTAL_NO_COINCIDE"
    assert "$130.00" in exc.value.detail["message"]
    assert _nada_escrito(mundo)
