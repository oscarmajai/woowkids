-- =============================================================================
-- 109_pin_tokens_proposito.sql
-- A16 (prueba E2E): el token de un solo uso que se emite al validar el PIN de
-- un administrador servía igual para cancelar una orden pagada que para cerrar
-- la caja, porque los dos usaban rol = 'admin'. Ahora cada token guarda para
-- qué se emitió y cada operación exige el suyo:
--   - 'cerrar':   revisión y confirmación del cierre de caja (también el token
--                 del cajero, que solo se usa en el cierre).
--   - 'cancelar': cancelaciones y devoluciones de órdenes cobradas.
-- Los tokens viejos (vigencia de 5 minutos) quedan como 'cerrar'.
-- Idempotente.
-- =============================================================================

ALTER TABLE public.pin_tokens
    ADD COLUMN IF NOT EXISTS proposito VARCHAR(20) NOT NULL DEFAULT 'cerrar';

-- El default solo sirve para rellenar las filas existentes: quien emite un
-- token siempre dice su propósito.
ALTER TABLE public.pin_tokens ALTER COLUMN proposito DROP DEFAULT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pin_tokens_proposito_check'
          AND conrelid = 'public.pin_tokens'::regclass
    ) THEN
        ALTER TABLE public.pin_tokens
            ADD CONSTRAINT pin_tokens_proposito_check
            CHECK (proposito IN ('cerrar', 'cancelar'));
    END IF;
END $$;
