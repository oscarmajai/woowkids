-- =============================================================================
-- 106_bitacora_respaldos.sql
-- Bloqueante de entrega: el sistema no se respaldaba solo. El proceso de
-- respaldos (scripts/respaldos.py) deja aquí una fila por intento, para que la
-- app avise al AdministradorSistema si los respaldos fallan o dejan de hacerse.
-- Idempotente.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.bitacora_respaldos (
    id         BIGSERIAL PRIMARY KEY,
    inicio     TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin        TIMESTAMPTZ,
    exitoso    BOOLEAN NOT NULL DEFAULT FALSE,
    motivo     VARCHAR(30) NOT NULL,
    nombre     TEXT,
    tamano_bd  BIGINT,
    archivos   INTEGER,
    error      TEXT
);

CREATE INDEX IF NOT EXISTS bitacora_respaldos_inicio_idx
    ON public.bitacora_respaldos (inicio DESC);
