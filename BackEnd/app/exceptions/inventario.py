"""Errores de dominio de inventario y compras: cantidades que no caben en el
inventario (M3)."""

from fastapi import HTTPException, status


class CantidadFueraDeRangoError(HTTPException):
    """Una cantidad ya convertida a la unidad base del insumo no cabe en el
    inventario: es menor a 0.001 o mayor al máximo (M3)."""

    def __init__(self, mensaje: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "CANTIDAD_FUERA_DE_RANGO", "message": mensaje},
        )
