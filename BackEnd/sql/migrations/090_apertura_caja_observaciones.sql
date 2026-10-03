-- =============================================================================
-- 090_apertura_caja_observaciones.sql
-- B13 (pruebas E2E 2026-10-03): el formulario de apertura de caja manda
-- "Notas" (observaciones_apertura), pero apertura_caja no tenía dónde
-- guardarlas y el texto se perdía sin avisar. Columna opcional; las aperturas
-- existentes quedan en NULL. Solo aditiva e idempotente.
-- =============================================================================

ALTER TABLE public.apertura_caja
    ADD COLUMN IF NOT EXISTS observaciones_apertura TEXT;
