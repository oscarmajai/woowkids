-- =============================================================================
-- 100_turnos_sucursal.sql
-- Los horarios de trabajo (tabla `turnos`) eran
-- un catálogo global: todas las sucursales veían los de las demás en su
-- apertura de caja y en la pestaña Horarios.
--
-- Se agrega `turnos.sucursal_id`:
--   - NULL  = horario global (los que ya existen quedan así). Lo ven todas las
--             sucursales y solo el AdministradorSistema lo edita.
--   - <id>  = horario de esa sucursal. Lo ve y lo edita solo esa sucursal.
--
-- El nombre deja de ser único en todo el sistema y pasa a ser único por
-- sucursal (los globales forman su propio grupo), para que dos sucursales
-- puedan tener su "Matutino". El backend además impide que un horario de
-- sucursal se llame igual que uno global. La restricción nueva es más laxa que
-- la anterior, así que los datos existentes la cumplen.
-- Idempotente y solo aditiva sobre los datos.
-- =============================================================================

ALTER TABLE public.turnos
    ADD COLUMN IF NOT EXISTS sucursal_id UUID NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'turnos_sucursal_id_fkey'
    ) THEN
        ALTER TABLE public.turnos
            ADD CONSTRAINT turnos_sucursal_id_fkey
            FOREIGN KEY (sucursal_id) REFERENCES public.sucursales(id);
    END IF;
END $$;

COMMENT ON COLUMN public.turnos.sucursal_id IS
    'Sucursal dueña del horario; NULL = global (visible para todas, solo lo edita AdministradorSistema).';

CREATE UNIQUE INDEX IF NOT EXISTS uq_turnos_sucursal_nombre
    ON public.turnos (COALESCE(sucursal_id, '00000000-0000-0000-0000-000000000000'::uuid), nombre);

ALTER TABLE public.turnos DROP CONSTRAINT IF EXISTS turnos_nombre_key;
