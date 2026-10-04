export type NavBadgeTone = 'warn' | 'bad'

export interface NavItem {
  label: string
  icon: string
  routeName: string
  permission?: string
  /** Solo para este rol (p. ej. AdministradorSistema). */
  role?: string
}

export interface NavGroup {
  /** null = grupo raíz sin encabezado (Inicio). */
  label: string | null
  items: NavItem[]
}

export interface NavBadge {
  count: number
  tone: NavBadgeTone
  /** De dónde sale el contador. Dos ítems con la misma fuente muestran el mismo
   * número y el grupo lo cuenta una sola vez (B7). */
  fuente?: string
}
