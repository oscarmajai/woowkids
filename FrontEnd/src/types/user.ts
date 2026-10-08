import type { UserRole } from './auth'

export interface UserListItem {
  id: string
  name: string
  lastName: string | null
  phone: string | null
  email: string
  role: UserRole
  branchId: string | null
  isActive: boolean
  lastAccess: string | null
  /** `true` si el usuario ya tiene PIN de caja configurado. */
  tienePin: boolean
  /**
   * Todas las sucursales del usuario. Un Administrador no tiene `branchId`
   * (se asigna desde la sucursal y puede tener varias): solo aparece aquí.
   */
  branchIds: string[]
}

export interface CreateUserPayload {
  name: string
  lastName?: string | null
  phone?: string | null
  email: string
  password: string
  role: UserRole
  branchId?: string | null
  /** PIN de caja de 4 dígitos, opcional. */
  pin?: string | null
}

export interface UpdateUserPayload {
  name: string
  lastName?: string | null
  phone?: string | null
  email: string
  role: UserRole
  branchId?: string | null
  password?: string | null
  isActive?: boolean | null
  /** PIN de caja de 4 dígitos. null/omitido = no cambiar. */
  pin?: string | null
}

/** Filtro de estado de GET /usuarios. Sin él, el backend lista solo activos. */
export type EstadoUsuarios = 'activos' | 'inactivos' | 'todos'
