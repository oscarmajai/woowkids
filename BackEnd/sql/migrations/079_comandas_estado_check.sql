-- =============================================================================
-- 079_comandas_estado_check.sql
-- comandas.estado_actual (VARCHAR(1)) no tenía ninguna restricción y el
-- PATCH /comandas/{id}/estado guardaba cualquier valor ("X", "" ...). La
-- máquina de estados ahora vive en comanda_service.cambiar_estado; este CHECK
-- es la red de seguridad en la BD: solo P (pendiente), E (en preparación),
-- L (lista), T (entregada) y C (cancelada), los valores de EstadoComanda.
--
-- NOT VALID: las pruebas por API pudieron dejar filas con valores inválidos en
-- instalaciones existentes. El CHECK aplica de inmediato a inserts y updates;
-- solo se valida contra las filas viejas si todas cumplen (en una BD nueva o
-- limpia queda validado). Si hay filas inválidas, la migración no falla ni las
-- toca: se pueden corregir a mano y luego correr
--   ALTER TABLE public.comandas VALIDATE CONSTRAINT chk_comandas_estado_actual;
-- Idempotente.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_comandas_estado_actual'
          AND conrelid = 'public.comandas'::regclass
    ) THEN
        ALTER TABLE public.comandas
            ADD CONSTRAINT chk_comandas_estado_actual
            CHECK (estado_actual IN ('P', 'E', 'L', 'T', 'C')) NOT VALID;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.comandas
        WHERE estado_actual NOT IN ('P', 'E', 'L', 'T', 'C')
    ) THEN
        ALTER TABLE public.comandas VALIDATE CONSTRAINT chk_comandas_estado_actual;
    END IF;
END $$;
