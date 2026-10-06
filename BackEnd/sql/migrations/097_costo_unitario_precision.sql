-- =============================================================================
-- 097_costo_unitario_precision.sql
-- insumos.costo_unitario era numeric(10,2). En insumos que se manejan en
-- gramos o mililitros el costo por unidad base es de centavos o fracciones
-- (aceite $0.042692/ml se guardaba como 0.04, -6 %), así que el "Valor del
-- inventario" y las entradas manuales (que se costean al promedio) salían mal.
-- Las capas guardaban 4 decimales y las líneas de compra 2 (una compra en g o
-- ml a $0.123/g se truncaba a $0.12).
--
-- Amplía a numeric(14,6) el costo unitario de:
--   - insumos.costo_unitario            (promedio vigente de las capas)
--   - capas_costo_insumo.costo_unitario (costo PEPS de cada entrada)
--   - detalle_compras.costo_unitario    (costo por unidad/presentación comprada)
--
-- Solo agranda precisión y escala: ningún valor existente cambia ni se pierde.
-- detalle_compras.subtotal es una columna generada a partir de costo_unitario y
-- PostgreSQL no deja cambiar el tipo de una columna usada por una generada: se
-- quita y se vuelve a crear con la misma expresión y el mismo tipo (sus valores
-- se recalculan de cantidad * costo_unitario, que no cambian). Idempotente: si
-- la columna ya tiene escala 6, no hace nada.
-- =============================================================================

ALTER TABLE public.insumos
    ALTER COLUMN costo_unitario TYPE numeric(14,6);

ALTER TABLE public.capas_costo_insumo
    ALTER COLUMN costo_unitario TYPE numeric(14,6);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'detalle_compras'
          AND column_name = 'costo_unitario'
          AND numeric_scale IS DISTINCT FROM 6
    ) THEN
        ALTER TABLE public.detalle_compras DROP COLUMN IF EXISTS subtotal;
        ALTER TABLE public.detalle_compras
            ALTER COLUMN costo_unitario TYPE numeric(14,6);
        ALTER TABLE public.detalle_compras
            ADD COLUMN subtotal numeric(10,2)
            GENERATED ALWAYS AS ((cantidad * costo_unitario)) STORED;
    END IF;
END $$;
