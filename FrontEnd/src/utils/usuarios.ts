import type { UserListItem } from '@/types/user'

/** Rol técnico sin sucursal: incluye la cuenta de sistema (comandas automáticas). */
export const ROL_SISTEMA = 'AdministradorSistema'
export const ROL_ADMINISTRADOR = 'Administrador'

type UsuarioBasico = Pick<UserListItem, 'id' | 'role'>
type UsuarioConSucursales = Pick<UserListItem, 'branchId' | 'branchIds'>

/**
 * Cuentas que no se editan ni se eliminan desde la UI: la propia (nadie se
 * borra ni se desactiva a sí mismo) y las de AdministradorSistema, incluida
 * `sistema@mercury.internal`. El backend también las rechaza.
 */
export function esCuentaProtegida(user: UsuarioBasico, usuarioActualId: string | null): boolean {
  return user.role === ROL_SISTEMA || (!!usuarioActualId && user.id === usuarioActualId)
}

/** Ids de las sucursales del usuario, sea con sucursal fija o Administrador. */
export function sucursalesDe(user: UsuarioConSucursales): string[] {
  if (user.branchIds?.length) return user.branchIds
  return user.branchId ? [user.branchId] : []
}

export function perteneceASucursal(user: UsuarioConSucursales, sucursalId: string): boolean {
  return sucursalesDe(user).includes(sucursalId)
}

/** Nombres de sus sucursales separados por coma, o "—" si no tiene. */
export function nombresSucursales(
  user: UsuarioConSucursales,
  sucursales: { id: string; nombre: string }[],
): string {
  const nombres = sucursalesDe(user)
    .map((id) => sucursales.find((s) => s.id === id)?.nombre)
    .filter((n): n is string => !!n)
  return nombres.length ? nombres.join(', ') : '—'
}
