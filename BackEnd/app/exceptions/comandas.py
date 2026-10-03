"""Errores de dominio de comandas: máquina de estados (A2) y cancelación de
comandas cobradas con devolución y autorización de administrador (A4)."""

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


class TurnoNoAbiertoParaDevolucionError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "TURNO_NO_ABIERTO",
                "message": (
                    "La orden ya está pagada: para cancelarla necesitas un turno de caja "
                    "abierto (operando), donde se registra la devolución al cliente."
                ),
            },
        )


class VentaDeTurnoCerradoError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "VENTA_DE_TURNO_CERRADO",
                "message": (
                    "La orden se cobró en un turno de caja que ya se cerró; su arqueo ya "
                    "no se puede modificar, así que no se puede cancelar."
                ),
            },
        )


class AutorizacionAdminRequeridaError(HTTPException):
    """Cancelar una comanda cobrada exige el token de PIN de un administrador
    (POST /turnos-caja/validar-pin-admin con el turno_id que viaja aquí)."""

    def __init__(self, turno_id: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "AUTORIZACION_ADMIN_REQUERIDA",
                "message": (
                    "La orden ya está pagada: cancelarla requiere la autorización con PIN "
                    "de un administrador de la sucursal."
                ),
                "turno_id": turno_id,
            },
        )


class AdminNoAutorizadoError(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ADMIN_NO_AUTORIZADO",
                "message": (
                    "Quien autoriza debe ser un administrador activo de la sucursal de la orden."
                ),
            },
        )


class ComandaPagadaRequiereCancelacionError(HTTPException):
    """Quitar todos los productos de una comanda cobrada equivale a cancelarla:
    debe ir por la cancelación con autorización y devolución."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "COMANDA_PAGADA_USAR_CANCELAR",
                "message": (
                    "La orden ya está pagada: para quitar todos los productos usa "
                    "«Cancelar orden», que registra la devolución con autorización "
                    "de un administrador."
                ),
            },
        )
