-- =============================================================================
-- 104_pagos_estancia_notas_pago.sql
-- El cobro de estancias (check-in, cargo extra del checkout y pago extra)
-- no tenía dónde guardar la referencia del pago (folio del voucher, número de
-- transferencia), así que no se podía exigir para los métodos que la piden
-- (el POS ya lo hace con pagos_ordenes.notas_pago). Columna opcional:
-- los pagos existentes quedan en NULL. Idempotente.
-- =============================================================================

ALTER TABLE public.pagos_estancia
    ADD COLUMN IF NOT EXISTS notas_pago TEXT NULL;
