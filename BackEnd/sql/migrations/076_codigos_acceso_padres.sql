-- =============================================================================
-- 076_codigos_acceso_padres.sql
-- A17: el código del QR del portal de padres era el UUID del registro, impreso
-- en el comprobante y sin caducidad. Ahora es un código opaco y aleatorio que
-- se emite al registrar la entrada. Solo se guarda su sha256 (nunca el código
-- en claro). Deja de valer cuando:
--   - caduca (`expira`, tope de 24 h desde la emisión),
--   - se revoca (`revocado`): al hacer checkout del último niño del registro o
--     al emitir un código nuevo para el mismo registro,
--   - o el registro deja de estar activo.
-- Los códigos viejos (UUID del registro) dejan de funcionar: no hay filas que
-- migrar.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.codigos_acceso_padres (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    registro_id UUID NOT NULL REFERENCES public.registros(id),
    codigo_hash CHAR(64) NOT NULL,
    expira      TIMESTAMPTZ NOT NULL,
    revocado    TIMESTAMPTZ,
    creado      TIMESTAMPTZ NOT NULL DEFAULT now(),
    creado_por  UUID,
    CONSTRAINT uq_codigos_acceso_padres_hash UNIQUE (codigo_hash)
);

CREATE INDEX IF NOT EXISTS idx_codigos_acceso_padres_registro_vigentes
    ON public.codigos_acceso_padres (registro_id)
    WHERE revocado IS NULL;
