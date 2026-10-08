-- =============================================================================
-- 110_lealtad_pesos_por_punto.sql
-- La configuración de lealtad pedía un "% de retorno" y un "valor del punto",
-- y los dos movían los puntos que se ganaban: no quedaba claro qué controlaba
-- cada campo. Ahora se piden las dos cosas como las entiende el negocio:
--   - pesos_por_punto: cuánto hay que gastar para ganar 1 punto;
--   - valor_punto:     cuánto vale ese punto al canjear (sin cambio).
-- El retorno al cliente (valor_punto / pesos_por_punto) es solo un resultado.
--
-- Migración de lo existente: antes se ganaban total * pct / 100 / valor_punto
-- puntos, así que pesos_por_punto = 100 * valor_punto / pct da exactamente los
-- mismos puntos y el mismo retorno. Con valor_punto = 1: 1% queda en "por cada
-- $100, 1 punto" y 2% en "por cada $50". Una sucursal con 0% no otorgaba
-- puntos: queda con $100 por punto y el programa desactivado, para que siga
-- sin otorgarlos hasta que alguien lo configure.
-- Idempotente.
-- =============================================================================

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'configuracion_lealtad'
          AND column_name = 'porcentaje_retorno'
    ) THEN
        ALTER TABLE public.configuracion_lealtad
            ADD COLUMN IF NOT EXISTS pesos_por_punto NUMERIC(12, 2) NOT NULL DEFAULT 100;

        UPDATE public.configuracion_lealtad
        SET pesos_por_punto = ROUND(100 * valor_punto / porcentaje_retorno, 2)
        WHERE porcentaje_retorno > 0;

        UPDATE public.configuracion_lealtad
        SET activo = FALSE
        WHERE porcentaje_retorno = 0;

        ALTER TABLE public.configuracion_lealtad DROP COLUMN porcentaje_retorno;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'configuracion_lealtad_pesos_por_punto_check'
          AND conrelid = 'public.configuracion_lealtad'::regclass
    ) THEN
        ALTER TABLE public.configuracion_lealtad
            ADD CONSTRAINT configuracion_lealtad_pesos_por_punto_check
            CHECK (pesos_por_punto > 0);
    END IF;
END $$;
