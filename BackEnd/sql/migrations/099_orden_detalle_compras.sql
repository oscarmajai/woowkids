-- =============================================================================
-- 099_orden_detalle_compras.sql
-- UX compras: las líneas de una compra se listaban por nombre del insumo (el
-- id es un uuid aleatorio y no había otra columna de orden), así que el diálogo
-- de recepción y el detalle las mostraban en otro orden que el capturado.
--
-- Agrega `secuencia` (bigint, autoincremental) a detalle_compras: el orden en
-- que se insertaron las líneas. Las filas existentes se numeran en el orden
-- físico de la tabla (no hay otra referencia para ellas). Solo agrega una
-- columna, su secuencia y un índice. Idempotente.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'detalle_compras'
          AND column_name = 'secuencia'
    ) THEN
        CREATE SEQUENCE IF NOT EXISTS public.detalle_compras_secuencia_seq;
        ALTER TABLE public.detalle_compras
            ADD COLUMN secuencia bigint
            NOT NULL DEFAULT nextval('public.detalle_compras_secuencia_seq');
        ALTER SEQUENCE public.detalle_compras_secuencia_seq
            OWNED BY public.detalle_compras.secuencia;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_detalle_compras_compra_secuencia
    ON public.detalle_compras (compra_id, secuencia);
