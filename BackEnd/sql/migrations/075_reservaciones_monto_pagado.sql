-- =============================================================================
-- 075_reservaciones_monto_pagado.sql
-- El saldo de una reservación refleja TODO lo cobrado, no sólo el anticipo
-- (si no, había reservaciones liquidadas que el scheduler cancelaba "por falta de
-- pago", y saldos obsoletos en Reservaciones, Registrar pago, Resumen de
-- eventos y el check-in de "Evento / Fiesta").
--
-- Antes: saldo_pendiente = precio_total - anticipo, y ningún pago posterior
-- tocaba `anticipo`. Ahora:
--   monto_pagado    = SUM(pagos_reservacion.monto)
--                     - SUM(cambio entregado en caja por esa reservación)
--   saldo_pendiente = precio_total - monto_pagado   (columna generada)
--
-- El anticipo ya se registra como un pago más en pagos_reservacion (tipo
-- 'anticipo'), así que sumarlo aparte lo contaría dos veces; `anticipo` queda
-- como dato histórico de lo cobrado al reservar. Los pagos guardan lo que el
-- cliente ENTREGÓ y el cambio sale como movimiento 'C' de caja con
-- referencia_id = reservación (pagos_reservacion.completar), por eso se resta.
--
-- monto_pagado lo mantiene el backend (pagos_reservacion service) en la misma
-- transacción de cada alta, edición o baja de pago, con la reservación
-- bloqueada (SELECT ... FOR UPDATE) para que dos cobros simultáneos no se
-- pisen el total.
--
-- PostgreSQL 16 no tiene ALTER COLUMN ... SET EXPRESSION: la columna generada
-- se elimina y se vuelve a crear (queda al final de la tabla; las consultas
-- nombran sus columnas, así que el orden no importa).
--
-- No cambia el estado de ninguna reservación: las que el scheduler canceló por
-- error se quedan como están (ver el reporte del fix para identificarlas).
-- =============================================================================

ALTER TABLE public.reservaciones
    ADD COLUMN IF NOT EXISTS monto_pagado numeric(10,2) DEFAULT 0 NOT NULL;

UPDATE public.reservaciones r
SET monto_pagado =
      COALESCE((SELECT SUM(pr.monto)
                  FROM public.pagos_reservacion pr
                 WHERE pr.reservacion_id = r.id), 0)
    - COALESCE((SELECT SUM(mc.monto)
                  FROM public.movimientos_caja mc
                 WHERE mc.tipo_movimiento = 'C'
                   AND mc.referencia_id = r.id), 0);

ALTER TABLE public.reservaciones DROP COLUMN IF EXISTS saldo_pendiente;

ALTER TABLE public.reservaciones
    ADD COLUMN saldo_pendiente numeric(10,2)
    GENERATED ALWAYS AS (precio_total - monto_pagado) STORED;

COMMENT ON COLUMN public.reservaciones.monto_pagado IS
    'Neto cobrado: suma de pagos_reservacion menos el cambio entregado. Lo mantiene el backend.';
COMMENT ON COLUMN public.reservaciones.anticipo IS
    'Lo cobrado al levantar la reservación (histórico). El saldo usa monto_pagado.';
