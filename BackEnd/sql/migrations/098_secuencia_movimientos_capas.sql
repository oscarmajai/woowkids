-- =============================================================================
-- 098_secuencia_movimientos_capas.sql
-- Los movimientos de una misma transacción (las líneas de una compra o de
-- una comanda) llevan el mismo `creado` (now() es la hora de inicio de la
-- transacción) y el kardex los ordenaba de forma arbitraria: la columna Saldo
-- salía fuera de secuencia. Lo mismo con las capas de costo PEPS de una misma
-- recepción: su orden de consumo dependía de un uuid aleatorio.
--
-- Agrega `secuencia` (bigint, autoincremental) a movimientos_inventario y a
-- capas_costo_insumo. Es el orden real de inserción y el desempate estable del
-- kardex y del PEPS. Las filas existentes se numeran por (creado, id), el
-- orden que ya usaban, así que el historial no cambia de orden.
--
-- Solo agrega columnas, secuencias e índices; no modifica datos de negocio.
-- Idempotente.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'movimientos_inventario'
          AND column_name = 'secuencia'
    ) THEN
        CREATE SEQUENCE IF NOT EXISTS public.movimientos_inventario_secuencia_seq;
        ALTER TABLE public.movimientos_inventario ADD COLUMN secuencia bigint;
        UPDATE public.movimientos_inventario m
        SET secuencia = o.n
        FROM (
            SELECT id, row_number() OVER (ORDER BY creado, id) AS n
            FROM public.movimientos_inventario
        ) o
        WHERE o.id = m.id;
        PERFORM setval(
            'public.movimientos_inventario_secuencia_seq',
            COALESCE((SELECT max(secuencia) FROM public.movimientos_inventario), 0) + 1,
            false
        );
        ALTER TABLE public.movimientos_inventario
            ALTER COLUMN secuencia SET DEFAULT nextval('public.movimientos_inventario_secuencia_seq');
        ALTER TABLE public.movimientos_inventario ALTER COLUMN secuencia SET NOT NULL;
        ALTER SEQUENCE public.movimientos_inventario_secuencia_seq
            OWNED BY public.movimientos_inventario.secuencia;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_movimientos_inventario_insumo_secuencia
    ON public.movimientos_inventario (insumo_id, secuencia);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'capas_costo_insumo'
          AND column_name = 'secuencia'
    ) THEN
        CREATE SEQUENCE IF NOT EXISTS public.capas_costo_insumo_secuencia_seq;
        ALTER TABLE public.capas_costo_insumo ADD COLUMN secuencia bigint;
        UPDATE public.capas_costo_insumo c
        SET secuencia = o.n
        FROM (
            SELECT id, row_number() OVER (ORDER BY creado, id) AS n
            FROM public.capas_costo_insumo
        ) o
        WHERE o.id = c.id;
        PERFORM setval(
            'public.capas_costo_insumo_secuencia_seq',
            COALESCE((SELECT max(secuencia) FROM public.capas_costo_insumo), 0) + 1,
            false
        );
        ALTER TABLE public.capas_costo_insumo
            ALTER COLUMN secuencia SET DEFAULT nextval('public.capas_costo_insumo_secuencia_seq');
        ALTER TABLE public.capas_costo_insumo ALTER COLUMN secuencia SET NOT NULL;
        ALTER SEQUENCE public.capas_costo_insumo_secuencia_seq
            OWNED BY public.capas_costo_insumo.secuencia;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_capas_insumo_fifo_secuencia
    ON public.capas_costo_insumo (insumo_id, secuencia)
    WHERE cantidad_restante > 0;
