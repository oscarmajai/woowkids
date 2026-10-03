-- =============================================================================
-- 089_usuarios_email_minusculas.sql
-- M1: los correos distinguían mayúsculas (uq_usuarios_email es sensible a
-- ellas): se podían crear dos cuentas con el mismo correo escrito distinto y
-- el login fallaba con otra capitalización. El backend ya guarda y busca los
-- correos en minúsculas; aquí:
--   1. Se pasan a minúsculas (y sin espacios alrededor) los correos existentes
--      que no choquen con otra cuenta. Los que chocan se dejan como están.
--   2. Se crea el índice único sobre lower(email), SOLO si no hay duplicados.
--      Si los hay, no se crea (para no impedir que el backend arranque) y se
--      emite un WARNING con los correos repetidos: hay que resolverlos a mano
--      (desactivar/renombrar la cuenta sobrante) y volver a crear el índice
--      con la misma sentencia de abajo.
-- Idempotente: se puede correr varias veces.
-- =============================================================================

UPDATE public.usuarios u
SET email = lower(btrim(u.email))
WHERE u.email <> lower(btrim(u.email))
  AND NOT EXISTS (
      SELECT 1
      FROM public.usuarios o
      WHERE o.id <> u.id
        AND lower(btrim(o.email)) = lower(btrim(u.email))
  );

DO $$
DECLARE
    v_duplicados TEXT;
BEGIN
    SELECT string_agg(correo, ', ' ORDER BY correo)
      INTO v_duplicados
      FROM (
          SELECT lower(email) AS correo
          FROM public.usuarios
          GROUP BY lower(email)
          HAVING count(*) > 1
      ) d;

    IF v_duplicados IS NOT NULL THEN
        RAISE WARNING
            '089: no se creó uq_usuarios_email_lower porque hay correos repetidos sin distinguir mayúsculas: %. Resuélvelos y crea el índice a mano.',
            v_duplicados;
    ELSE
        CREATE UNIQUE INDEX IF NOT EXISTS uq_usuarios_email_lower
            ON public.usuarios (lower(email));
    END IF;
END $$;
