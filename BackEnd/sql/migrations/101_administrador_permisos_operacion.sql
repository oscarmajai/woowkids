-- =============================================================================
-- 101_administrador_permisos_operacion.sql
-- Decisión de negocio: el Administrador (rol_id=2) debe tener
-- todos los permisos salvo los del sistema. Se le otorgan los que hasta ahora
-- solo tenía el AdministradorSistema (rol_id=1) y que son de la operación de
-- una sucursal:
--   - inventario:eliminar_producto (desactivar un producto exige
--     el mismo permiso que eliminarlo y el Administrador se había quedado sin
--     ninguna vía para hacerlo);
--   - retiros_parciales:crear y turnos_caja:ingreso_efectivo (el
--     Administrador abre y cierra su turno desde la 073);
--   - reportes:usuarios.
-- Quedan solo para el AdministradorSistema los del sistema:
-- sucursales:crear/editar/eliminar (alta y baja de la franquicia) y
-- permisos:editar (los roles son globales a todas las sucursales).
-- Idempotente.
-- =============================================================================

INSERT INTO public.rol_permisos (rol_id, permiso_id)
SELECT 2, p.id
FROM public.permisos p
WHERE p.codigo IN (
    'inventario:eliminar_producto',
    'retiros_parciales:crear',
    'turnos_caja:ingreso_efectivo',
    'reportes:usuarios'
)
AND NOT EXISTS (
    SELECT 1 FROM public.rol_permisos rp WHERE rp.rol_id = 2 AND rp.permiso_id = p.id
);
