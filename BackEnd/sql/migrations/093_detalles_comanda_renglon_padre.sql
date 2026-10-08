-- =============================================================================
-- 093_detalles_comanda_renglon_padre.sql
-- Los productos de un combo (es_hijo_combo) guardaban en es_hijo_de el
-- producto_id del combo, no el renglón padre. Con dos renglones del mismo
-- combo (combo dividido para personalizar) el ticket y "Editar orden" no
-- sabían qué hijos eran de cuál y repetían todos bajo cada combo.
--
-- detalle_padre_id apunta al renglón (detalles_comanda.id) del combo al que
-- pertenece el hijo. NULL en productos sueltos, en renglones de combo y en
-- filas viejas que no se pueden asignar sin ambigüedad (el front las sigue
-- agrupando como antes). ON DELETE CASCADE: quitar el renglón de un combo
-- quita también su contenido.
--
-- Backfill: solo cuando la comanda tiene UN renglón de ese combo (entonces
-- todos sus hijos son de ese renglón). Con varios renglones del mismo combo
-- no hay forma segura de saber el orden original y se dejan en NULL.
-- Idempotente.
-- =============================================================================

ALTER TABLE public.detalles_comanda
    ADD COLUMN IF NOT EXISTS detalle_padre_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_detalles_comanda_detalle_padre'
          AND conrelid = 'public.detalles_comanda'::regclass
    ) THEN
        ALTER TABLE public.detalles_comanda
            ADD CONSTRAINT fk_detalles_comanda_detalle_padre
            FOREIGN KEY (detalle_padre_id) REFERENCES public.detalles_comanda(id)
            ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_detalles_comanda_detalle_padre
    ON public.detalles_comanda (detalle_padre_id)
    WHERE detalle_padre_id IS NOT NULL;

WITH padres_unicos AS (
    SELECT comanda_id, producto_id, (array_agg(id))[1] AS padre_id
    FROM public.detalles_comanda
    WHERE NOT es_hijo_combo
    GROUP BY comanda_id, producto_id
    HAVING COUNT(*) = 1
)
UPDATE public.detalles_comanda h
SET detalle_padre_id = pu.padre_id
FROM padres_unicos pu
WHERE h.es_hijo_combo
  AND h.detalle_padre_id IS NULL
  AND h.es_hijo_de IS NOT NULL
  AND pu.comanda_id = h.comanda_id
  AND pu.producto_id = h.es_hijo_de;
