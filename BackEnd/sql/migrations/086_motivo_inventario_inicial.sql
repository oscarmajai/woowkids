-- =============================================================================
-- 086_motivo_inventario_inicial.sql
-- El stock inicial con el que se da de alta un insumo no generaba
-- movimiento ni capa de costo (el kardex no cuadraba y quedaban unidades sin
-- costo para el PEPS). Ahora insumo_service.crear registra una entrada con este
-- motivo. Solo agrega el valor al ENUM; no toca filas existentes.
-- =============================================================================

ALTER TYPE public.motivo_movimiento_inventario ADD VALUE IF NOT EXISTS 'inventario_inicial';
