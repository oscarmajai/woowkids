-- =============================================================================
-- 105_seguridad_arranque.sql
-- Bloqueante de entrega: el sistema arrancaba con SECRET_KEY y contraseña del
-- administrador inicial de fábrica.
--
-- 1. secretos_sistema: si la instalación no define su propia SECRET_KEY (o deja
--    la de fábrica), el entrypoint genera una aleatoria la primera vez y la
--    guarda aquí para que sobreviva reinicios y actualizaciones de la imagen.
-- 2. usuarios.debe_cambiar_password: mientras esté en TRUE, la API solo deja
--    al usuario cambiar su contraseña (lo marca el administrador inicial y quien
--    entra con la contraseña de fábrica).
-- Idempotente.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.secretos_sistema (
    nombre TEXT PRIMARY KEY,
    valor  TEXT NOT NULL,
    creado TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.usuarios
    ADD COLUMN IF NOT EXISTS debe_cambiar_password BOOLEAN NOT NULL DEFAULT FALSE;
