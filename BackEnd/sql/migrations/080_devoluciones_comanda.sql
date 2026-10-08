-- =============================================================================
-- 080_devoluciones_comanda.sql
-- Cancelar una comanda ya cobrada no movía la caja: el efectivo esperado
-- del arqueo seguía contando la venta. Ahora la cancelación de una comanda con
-- pagos (autorizada con el PIN de un administrador) registra aquí la
-- devolución al cliente, en el turno de caja abierto de quien cancela:
--   - es_efectivo = TRUE: lo que sale del cajón (efectivo cobrado menos el
--     cambio que ya se había entregado). Resta del efectivo esperado del
--     arqueo (caja_repository.calcular_efectivo_disponible y
--     turnos_caja_service._calcular_balance).
--   - es_efectivo = FALSE: pagos con tarjeta, transferencia, etc. Quedan
--     registrados como devueltos, sin mover el efectivo.
-- No es un movimientos_caja: todo tipo que no sea RP/C/I se suma ahí como
-- venta, y su CHECK exige monto > 0 sin signo.
-- Idempotente.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.devoluciones_comanda (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    comanda_id        UUID NOT NULL REFERENCES public.comandas(id),
    -- Turno de quien cancela: de su cajón sale el efectivo.
    apertura_caja_id  UUID NOT NULL REFERENCES public.apertura_caja(id),
    -- Turno en el que se cobró la venta (NULL si no hubo movimiento de caja).
    apertura_venta_id UUID REFERENCES public.apertura_caja(id),
    metodo_pago_id    UUID REFERENCES public.metodos_pago(id),
    es_efectivo       BOOLEAN NOT NULL,
    monto             NUMERIC(12,2) NOT NULL,
    autorizado_por    UUID NOT NULL REFERENCES public.usuarios(id),
    creado            TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por        UUID REFERENCES public.usuarios(id),
    CONSTRAINT chk_devoluciones_comanda_monto CHECK (monto > 0)
);

CREATE INDEX IF NOT EXISTS idx_devoluciones_comanda_apertura
    ON public.devoluciones_comanda (apertura_caja_id);

CREATE INDEX IF NOT EXISTS idx_devoluciones_comanda_comanda
    ON public.devoluciones_comanda (comanda_id);
