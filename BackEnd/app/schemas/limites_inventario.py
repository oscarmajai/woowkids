"""
app/schemas/limites_inventario.py
Límites de las cantidades y costos que llegan a inventario y compras (M3/M21).

Sin límites, una cantidad como `1e12` desbordaba `numeric(12,3)` y una como
`0.0004` pasaba `gt=0` pero se redondeaba a 0 en la columna y rompía su CHECK:
ambas respondían 500. Con estos límites responden 422 antes de tocar la BD.

Los decimales permitidos son los de la columna donde se guardan:
- cantidades y stock: `numeric(12,3)` → 3 decimales;
- costo unitario: `numeric(14,6)` (migración 097) → 6 decimales;
- montos de compra (IVA, subtotal, total): `numeric(10,2)` → 2 decimales.
"""

from __future__ import annotations

from decimal import Decimal

DECIMALES_CANTIDAD = 3
DECIMALES_COSTO = 6
DECIMALES_MONTO = 2

# Cantidad máxima de una línea, un movimiento o un nivel de stock: ~10 millones
# de unidades (10 toneladas en gramos). Deja margen en `numeric(12,3)` (máximo
# 999,999,999.999) para que el stock acumulado no desborde.
MAX_CANTIDAD = Decimal("9999999.999")

# Mínimo representable en una columna de 3 decimales.
MIN_CANTIDAD = Decimal("0.001")

# Costo unitario máximo (cabe en `numeric(14,6)`).
MAX_COSTO_UNITARIO = Decimal("9999999.999999")

# Monto máximo de una línea, del total o del IVA de una compra (`numeric(10,2)`).
MAX_MONTO_COMPRA = Decimal("99999999.99")
