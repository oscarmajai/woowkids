from typing import Literal

from fastapi import HTTPException, status


class CredencialesInvalidas(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": "Credenciales incorrectas."},
        )


class NoEncontrado(HTTPException):
    """404 con la frase concordada con el género del recurso (N15):
    `NoEncontrado("Reservación", genero="f")` → "Reservación no encontrada.".
    `mensaje` reemplaza la frase completa cuando no basta con el nombre."""

    def __init__(
        self,
        recurso: str = "Recurso",
        genero: Literal["m", "f"] = "m",
        *,
        mensaje: str | None = None,
    ) -> None:
        if mensaje is None:
            participio = "encontrada" if genero == "f" else "encontrado"
            mensaje = f"{recurso} no {participio}."
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": mensaje},
        )


class Conflicto(HTTPException):
    def __init__(self, mensaje: str = "El registro ya existe.") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CONFLICT", "message": mensaje},
        )


class DatosInvalidos(HTTPException):
    def __init__(self, mensaje: str = "Los datos enviados no son válidos.") -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_DATA", "message": mensaje},
        )


class StockInsuficienteError(HTTPException):
    def __init__(self, insumo_nombre: str, contexto: str = "completar la operación") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "STOCK_INSUFICIENTE",
                "message": f"No hay stock suficiente de «{insumo_nombre}» para {contexto}.",
            },
        )


class SaldoInsuficienteError(HTTPException):
    def __init__(self, saldo_disponible: int, contexto: str = "realizar el canje") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SALDO_INSUFICIENTE",
                "message": (
                    f"Saldo de puntos insuficiente (disponible: {saldo_disponible}) "
                    f"para {contexto}."
                ),
            },
        )


class IdempotenciaConflictoError(HTTPException):
    """La misma Idempotency-Key llegó con un payload distinto al original (QA #20)."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCIA_CONFLICTO",
                "message": "Esta clave de idempotencia ya se usó con datos distintos.",
            },
        )


class IdempotenciaEnCursoError(HTTPException):
    """M3: otro cobro con la misma Idempotency-Key se está registrando."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "IDEMPOTENCIA_EN_CURSO",
                "message": (
                    "Este cobro ya se está registrando. Revisa el historial de ventas "
                    "antes de volver a cobrar."
                ),
            },
        )


class PinTokenRequeridoError(HTTPException):
    """Falta token_pin de cajero/admin en /turnos-caja/confirmar (QA #14)."""

    def __init__(
        self, mensaje: str = "Se requieren los tokens de PIN de cajero y administrador."
    ) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "PIN_TOKEN_REQUERIDO", "message": mensaje},
        )


class PinTokenPropositoError(HTTPException):
    """A16: el token de PIN de administrador se emitió para otra operación
    (p. ej. uno de cancelar una orden presentado para cerrar la caja)."""

    def __init__(self, mensaje: str) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PIN_TOKEN_PROPOSITO_INVALIDO", "message": mensaje},
        )


class PrecioCambiadoError(HTTPException):
    """El precio o el total que mandó el cliente no coincide con el que
    calcula el servidor con el catálogo vigente (C2). No se cobra nada; el
    frontend debe refrescar el catálogo y volver a cobrar."""

    def __init__(self, mensaje: str, code: str = "PRECIO_CAMBIADO") -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": code, "message": mensaje},
        )


class ProductoNoDisponibleError(HTTPException):
    """El producto existe en la sucursal pero ya no está activo (C2)."""

    def __init__(self, nombre: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PRODUCTO_NO_DISPONIBLE",
                "message": f"«{nombre}» ya no está disponible. Actualiza el pedido.",
            },
        )


class PedidoInvalidoError(HTTPException):
    """El pedido no se puede procesar tal como viene: producto inexistente o de
    otra sucursal, cantidad fuera de rango, combo que no corresponde a su
    definición, pago sin referencia, etc. (C2, M3, M11)."""

    def __init__(self, mensaje: str, code: str = "PEDIDO_INVALIDO") -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": code, "message": mensaje},
        )


class RecepcionInvalidaError(HTTPException):
    """La recepción de una compra no se puede aplicar tal como viene: una línea
    excede lo pendiente, no pertenece a la compra, viene repetida o no trae nada
    que recibir (A12, M23). `linea` lleva el detalle de la línea culpable para
    que el cliente la señale."""

    def __init__(self, mensaje: str, linea: dict[str, str] | None = None) -> None:
        detail: dict[str, object] = {"code": "RECEPCION_INVALIDA", "message": mensaje}
        if linea is not None:
            detail["linea"] = linea
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
