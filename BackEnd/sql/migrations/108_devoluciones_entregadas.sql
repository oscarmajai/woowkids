-- =============================================================================
-- 108_devoluciones_entregadas.sql
-- A4 (segunda parte): devolución del dinero de una comanda ya entregada.
--   - origen: 'cancelacion' (la comanda se canceló en cocina, P/E/L, y su
--     stock regresó al inventario) o 'entregada' (la comanda ya se entregó: se
--     devuelve el dinero pero el producto ya se consumió y el stock NO
--     regresa).
--   - motivo: por qué se devolvió (el mismo motivo que queda en la comanda),
--     para que cada devolución del arqueo diga quién (creado_por), cuándo
--     (creado), quién autorizó (autorizado_por) y por qué.
-- Desde aquí todas las devoluciones bajan el esperado de su método en el
-- arqueo, no solo las de efectivo (turnos_caja_service._calcular_balance).
-- Las filas existentes son de cancelaciones: toman el origen por omisión y
-- su motivo se copia de la comanda.
-- Idempotente.
-- =============================================================================

ALTER TABLE public.devoluciones_comanda
    ADD COLUMN IF NOT EXISTS origen VARCHAR(12) NOT NULL DEFAULT 'cancelacion';

ALTER TABLE public.devoluciones_comanda
    ADD COLUMN IF NOT EXISTS motivo TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_devoluciones_comanda_origen'
    ) THEN
        ALTER TABLE public.devoluciones_comanda
            ADD CONSTRAINT chk_devoluciones_comanda_origen
            CHECK (origen IN ('cancelacion', 'entregada'));
    END IF;
END $$;

UPDATE public.devoluciones_comanda d
SET motivo = c.motivo_cancelacion
FROM public.comandas c
WHERE c.id = d.comanda_id
  AND d.motivo IS NULL
  AND c.motivo_cancelacion IS NOT NULL;
