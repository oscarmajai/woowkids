-- =============================================================================
-- 074_permiso_registrar_pago.sql
-- El cobro del POS (POST /pagos, /pagos/completar, historial y estadísticas de
-- ventas, edición de detalles de comanda) exige `restaurante:registrar_pago`,
-- pero ninguna migración creaba ese permiso: en una BD nueva nadie podía cobrar
-- una comanda, ni el AdministradorSistema. Se crea y se asigna a quienes operan
-- la caja o supervisan ventas (rol_id 1 = AdministradorSistema, 2 = Administrador,
-- 3 = Cajero; mismo patrón que 029/058).
-- =============================================================================

INSERT INTO public.permisos (codigo, nombre, modulo) VALUES
    ('restaurante:registrar_pago', 'Registrar pagos de comandas y ver historial de ventas', 'restaurante')
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO public.rol_permisos (rol_id, permiso_id)
SELECT r.id, p.id
FROM public.roles r
CROSS JOIN public.permisos p
WHERE r.id IN (1, 2, 3) AND p.codigo = 'restaurante:registrar_pago'
ON CONFLICT DO NOTHING;
