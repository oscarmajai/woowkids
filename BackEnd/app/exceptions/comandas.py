"""Errores de dominio de comandas: máquina de estados (A2)."""

from fastapi import HTTPException, status


class TransicionComandaInvalidaError(HTTPException):
    """El cambio de estado no sigue la máquina P → E → L → T (o C desde P/E/L)."""

    def __init__(self, mensaje: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "TRANSICION_COMANDA_INVALIDA", "message": mensaje},
        )


class ComandaCanceladaError(HTTPException):
    """La comanda está cancelada o inactiva: ya no admite cambios de estado."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "COMANDA_CANCELADA",
                "message": "La comanda está cancelada; ya no se puede cambiar su estado.",
            },
        )
