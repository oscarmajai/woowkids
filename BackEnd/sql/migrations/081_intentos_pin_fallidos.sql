-- =============================================================================
-- 081_intentos_pin_fallidos.sql
-- A16 (pruebas E2E 2026-10-03): los endpoints que validan el PIN de caja
-- (abrir turno, validar-pin-cajero, validar-pin-admin, revisión del
-- administrador) no limitaban los intentos, así que un PIN de 4 dígitos se
-- podía adivinar por fuerza bruta.
--
-- Cada intento fallido se registra por usuario objetivo (el dueño del PIN) y
-- sucursal. Con 5 fallos en 15 minutos el backend responde 429 hasta que el
-- más viejo de esos fallos sale de la ventana; un acierto limpia el contador.
-- Va en tabla (no en memoria) para que el límite valga con varios workers.
-- Solo aditiva: no toca datos existentes.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.intentos_pin_fallidos (
    id            BIGSERIAL   PRIMARY KEY,
    usuario_id    UUID        NOT NULL REFERENCES public.usuarios(id) ON DELETE CASCADE,
    sucursal_id   UUID        NULL REFERENCES public.sucursales(id) ON DELETE CASCADE,
    tipo          VARCHAR(20) NOT NULL,
    intentado_por UUID        NULL REFERENCES public.usuarios(id) ON DELETE SET NULL,
    creado        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.intentos_pin_fallidos IS
    'Intentos fallidos de PIN/contraseña de caja por usuario objetivo y sucursal (límite A16).';
COMMENT ON COLUMN public.intentos_pin_fallidos.tipo IS
    'Dónde se intentó: apertura, cajero, admin o revision.';
COMMENT ON COLUMN public.intentos_pin_fallidos.intentado_por IS
    'Usuario de la sesión que hizo el intento (puede ser distinto del dueño del PIN).';

CREATE INDEX IF NOT EXISTS idx_intentos_pin_usuario_sucursal
    ON public.intentos_pin_fallidos (usuario_id, sucursal_id, creado DESC);
