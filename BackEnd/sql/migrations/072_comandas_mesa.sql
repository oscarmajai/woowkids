-- 072_comandas_mesa.sql
-- Mesa del pedido, opcional, para la comanda de caja/cocina.

ALTER TABLE public.comandas
    ADD COLUMN IF NOT EXISTS mesa VARCHAR(20) NULL;
