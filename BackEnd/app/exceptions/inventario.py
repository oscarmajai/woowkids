"""Errores de dominio de inventario y compras: recursos eliminados, costo
unitario no editable y cantidades que no caben en el inventario."""

from fastapi import HTTPException, status


class RecursoInactivoError(HTTPException):
    """Operación sobre un insumo o proveedor eliminado (borrado lógico,
    `activo = FALSE`): no admite compras, movimientos ni presentaciones
    nuevas."""

    def __init__(self, mensaje: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "RECURSO_INACTIVO", "message": mensaje},
        )


class CostoNoEditableError(HTTPException):
    """El costo unitario de un insumo es el promedio PEPS de sus capas de
    costo y se recalcula en cada movimiento; no se edita a mano."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "COSTO_NO_EDITABLE",
                "message": (
                    "El costo unitario no se edita a mano: se calcula con el costo de "
                    "las compras y entradas (PEPS) y se actualiza en cada movimiento."
                ),
            },
        )


class CantidadFueraDeRangoError(HTTPException):
    """Una cantidad ya convertida a la unidad base del insumo no cabe en el
    inventario: es menor a 0.001 o mayor al máximo."""

    def __init__(self, mensaje: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "CANTIDAD_FUERA_DE_RANGO", "message": mensaje},
        )
