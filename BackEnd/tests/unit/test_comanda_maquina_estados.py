"""A2: máquina de estados de las comandas (lógica pura). Los casos con BD
(zombie, C → T → C, concurrencia, devolución) están en
tests/db/test_comandas_estados_cancelacion_pg.py."""

import pytest
from app.exceptions.comandas import ComandaCanceladaError, TransicionComandaInvalidaError
from app.services.comanda_service import validar_transicion


@pytest.mark.parametrize(
    ("actual", "nuevo"),
    [("P", "E"), ("E", "L"), ("L", "T"), ("P", "C"), ("E", "C"), ("L", "C")],
)
def test_transiciones_validas(actual: str, nuevo: str) -> None:
    validar_transicion(actual, True, nuevo)


@pytest.mark.parametrize(
    ("actual", "nuevo"),
    [
        ("E", "P"),  # retroceder
        ("T", "E"),
        ("L", "E"),
        ("P", "L"),  # saltar
        ("P", "T"),
        ("E", "T"),
        ("E", "E"),  # repetir
        ("T", "C"),  # entregada: terminal
        ("T", "T"),
        ("X", "E"),  # dato viejo inválido
        ("", "C"),
    ],
)
def test_transiciones_invalidas_409(actual: str, nuevo: str) -> None:
    with pytest.raises(TransicionComandaInvalidaError) as exc:
        validar_transicion(actual, True, nuevo)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("nuevo", ["P", "E", "L", "T", "C"])
def test_cancelada_o_inactiva_no_cambia(nuevo: str) -> None:
    with pytest.raises(ComandaCanceladaError):
        validar_transicion("C", False, nuevo)
    # Inactiva en un estado de cocina (el "zombie" de datos viejos).
    with pytest.raises(ComandaCanceladaError):
        validar_transicion("E", False, nuevo)
