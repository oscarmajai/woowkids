"""`NoEncontrado` concuerda en género con el recurso: "Reservación no
encontrada", "Insumo no encontrado". Los repositories se mockean (sin BD)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.exceptions import NoEncontrado
from app.repositories import reservaciones_repository
from app.schemas.auth import TokenData
from app.services import alcance_service, reservaciones


def _mensaje(exc: NoEncontrado) -> str:
    assert exc.status_code == 404
    assert isinstance(exc.detail, dict)
    assert exc.detail["code"] == "NOT_FOUND"
    return str(exc.detail["message"])


def test_masculino_por_omision():
    assert _mensaje(NoEncontrado("Insumo")) == "Insumo no encontrado."


def test_femenino():
    assert _mensaje(NoEncontrado("Reservación", genero="f")) == "Reservación no encontrada."


def test_mensaje_completo_reemplaza_la_frase():
    exc = NoEncontrado(mensaje="No hay ninguna caja con ese código.")
    assert _mensaje(exc) == "No hay ninguna caja con ese código."


async def test_service_de_reservaciones_usa_femenino(monkeypatch):
    async def fake_obtener(conn, reservacion_id):
        return None

    monkeypatch.setattr(reservaciones_repository, "obtener", fake_obtener)
    with pytest.raises(NoEncontrado) as exc_info:
        await reservaciones.obtener(None, uuid4())
    assert _mensaje(exc_info.value) == "Reservación no encontrada."


@pytest.mark.parametrize(
    ("tipo", "esperado"),
    [
        ("reservacion", "Reservación no encontrada."),
        ("compra", "Compra no encontrada."),
        ("pulsera", "Pulsera no encontrada."),
        ("presentacion_insumo", "Presentación no encontrada."),
        ("caja", "Caja no encontrada."),
        ("comanda", "Comanda no encontrada."),
        ("insumo", "Insumo no encontrado."),
        ("apertura_caja", "Turno no encontrado."),
        ("extra", "Extra no encontrado."),
    ],
)
async def test_alcance_por_sucursal_concuerda_en_genero(monkeypatch, tipo, esperado):
    """Un recurso de otra sucursal responde 404 con la frase concordada."""

    async def fake_sucursal_de(conn, tipo, recurso_id):
        return uuid4()  # siempre otra sucursal

    monkeypatch.setattr(alcance_service.alcance_repository, "sucursal_de", fake_sucursal_de)
    usuario = TokenData(
        sub=str(uuid4()),
        email="x@y.z",
        role="Cajero",
        branch_id=uuid4(),
        jti=str(uuid4()),
        exp=datetime.now(UTC),
    )
    with pytest.raises(NoEncontrado) as exc_info:
        await alcance_service.asegurar_recurso(None, usuario, tipo, uuid4())
    assert _mensaje(exc_info.value) == esperado


async def test_alcance_con_id_invalido_concuerda_en_genero():
    usuario = TokenData(
        sub=str(uuid4()),
        email="x@y.z",
        role="Cajero",
        branch_id=uuid4(),
        jti=str(uuid4()),
        exp=datetime.now(UTC),
    )
    with pytest.raises(NoEncontrado) as exc_info:
        await alcance_service.asegurar_recurso(None, usuario, "reservacion", "no-es-uuid")
    assert _mensaje(exc_info.value) == "Reservación no encontrada."
