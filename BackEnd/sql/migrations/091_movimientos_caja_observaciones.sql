-- =============================================================================
-- 091_movimientos_caja_observaciones.sql
-- UX caja (pruebas E2E 2026-10-03): el ingreso de efectivo no tenía campo de
-- motivo (los retiros sí: retiros_parciales.observaciones). Los ingresos viven
-- en movimientos_caja (tipo 'I') sin tabla propia, así que el motivo va en una
-- columna opcional de esa tabla. Las filas existentes quedan en NULL. Solo
-- aditiva e idempotente.
-- =============================================================================

ALTER TABLE public.movimientos_caja
    ADD COLUMN IF NOT EXISTS observaciones TEXT;
