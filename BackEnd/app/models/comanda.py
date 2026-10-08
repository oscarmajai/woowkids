"""
app/models/comanda.py
Entidades de dominio — dataclasses puros, sin ORM.
Regla 11.1 SAD: prohibido SQLAlchemy en este proyecto.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass
class DetalleComanda:
    id: str
    comanda_id: str
    producto_id: str
    cantidad: int
    precio_unitario: Decimal
    importe: Decimal
    sucursal_id: str
    notas_especiales: str | None = None
    # Datos del producto (join opcional al leer)
    nombre: str | None = None
    producto_nombre: str | None = None
    producto_tipo: str | None = None
    # Origen del combo — persistidos en BD para evitar ambigüedad
    nombre_combo_padre: str | None = None
    es_hijo_de: str | None = None
    es_hijo_combo: bool = False
    # Instancia de combo: agrupa hijos de una misma unidad pedida (KDS)
    id_combo_padre: str | None = None
    # Renglón (detalles_comanda.id) del combo al que pertenece el hijo.
    # None en productos sueltos, renglones de combo y filas viejas ambiguas.
    detalle_padre_id: str | None = None


@dataclass
class Comanda:
    id: str
    ticket_numero: str
    estado_actual: str  # valor del enum EstadoComanda, ej. 'P'
    total_final: Decimal
    sucursal_id: str
    fecha_hora: datetime | None = None
    nombre_cliente: str | None = None
    mesa: str | None = None
    # expandir_detalles_comanda() reemplaza esta lista por dicts (uno por
    # producto hijo cuando hay combos) — no siempre son DetalleComanda.
    detalles: list[DetalleComanda | dict[str, Any]] = field(default_factory=list)


def _campo(detalle: Any, nombre: str) -> Any:
    if isinstance(detalle, dict):
        return detalle.get(nombre)
    return getattr(detalle, nombre, None)


def indices_renglon_padre(detalles: Sequence[Any]) -> list[int | None]:
    """Para cada detalle de un pedido, el índice (en `detalles`) del
    renglón de combo al que pertenece, o None si no es hijo de combo.

    Cada renglón de combo con cantidad N aporta N unidades; las unidades de
    hijos (`id_combo_padre`, una por unidad de combo vendida) se reparten entre
    los renglones de ese combo en el orden en que aparecen. Así un combo
    dividido (dos renglones de cantidad 1) y un 2x combo (un renglón de
    cantidad 2) quedan cada uno con sus propios hijos. Un hijo sin unidad
    (datos viejos) va al primer renglón de su combo.

    Acepta DetalleCreate o dicts (producto en `id`/`producto_id`)."""
    unidades: dict[str, list[int]] = {}
    for i, d in enumerate(detalles):
        if _campo(d, "es_hijo_combo"):
            continue
        producto_id = _campo(d, "producto_id") or _campo(d, "id")
        cantidad = int(_campo(d, "cantidad") or 1)
        unidades.setdefault(str(producto_id), []).extend([i] * max(cantidad, 1))

    asignadas: dict[tuple[str, str], int] = {}
    siguiente: dict[str, int] = {}
    resultado: list[int | None] = []
    for d in detalles:
        combo = _campo(d, "es_hijo_de")
        if not _campo(d, "es_hijo_combo") or not combo or not unidades.get(str(combo)):
            resultado.append(None)
            continue
        disponibles = unidades[str(combo)]
        instancia = _campo(d, "id_combo_padre")
        if not instancia:
            resultado.append(disponibles[0])
            continue
        clave = (str(combo), str(instancia))
        if clave not in asignadas:
            n = siguiente.get(str(combo), 0)
            asignadas[clave] = disponibles[min(n, len(disponibles) - 1)]
            siguiente[str(combo)] = n + 1
        resultado.append(asignadas[clave])
    return resultado
