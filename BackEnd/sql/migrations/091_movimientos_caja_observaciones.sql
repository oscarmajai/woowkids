-- =============================================================================
-- 091_movimientos_caja_observaciones.sql
-- El ingreso de efectivo de caja no tenía campo de
-- motivo (los retiros sí: retiros_parciales.observaciones). Los ingresos viven
-- en movimientos_caja (tipo 'I') sin tabla propia, así que el motivo va en una
-- columna opcional de esa tabla. Las filas existentes quedan en NULL. Solo
-- aditiva e idempotente.
-- =============================================================================

ALTER TABLE public.movimientos_caja
    ADD COLUMN IF NOT EXISTS observaciones TEXT;
