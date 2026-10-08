-- =============================================================================
-- 041_sucursales_modificado_nullable.sql
-- Sigue de 039_fix_modificado_default_auditoria.sql. El UPDATE de sucursales de
-- esa migración falla con NotNullViolationError:
-- a diferencia de cajas/turnos/apertura_caja (nullable desde su creación en
-- 020_corte_caja.sql), sucursales.modificado quedó NOT NULL desde el esquema
-- original del proyecto (001_initial_schema.sql) — una inconsistencia previa,
-- no una decisión deliberada de que sucursales se comporte distinto.
--
-- El mismo criterio de auditoría (modificado = NULL hasta que
-- exista una modificación real) aplica igual a sucursales, que también entra
-- en el criterio (cajas, turnos, apertura_caja, cierre_caja,
-- retiros_parciales, movimientos_caja, sucursales...). Se libera el NOT NULL
-- y se completa el UPDATE que 039 dejó pendiente para esta tabla.
--
-- Nota: usuarios y usuarios_sucursal tienen el mismo NOT NULL heredado de
-- 001_initial_schema.sql. Quedan fuera de este fix: no son parte del módulo
-- de Caja y no entran en este criterio.
-- =============================================================================

ALTER TABLE public.sucursales ALTER COLUMN modificado DROP NOT NULL;

UPDATE public.sucursales
SET modificado = NULL
WHERE modificado IS NOT NULL AND modificado_por IS NULL;
