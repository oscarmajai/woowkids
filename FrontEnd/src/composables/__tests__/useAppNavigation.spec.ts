import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * UX shell: el menú de AdministradorSistema ofrecía Caja (POS) y Apertura y
 * Cierre sin sucursal elegida (no tiene sucursal propia ni turno).
 */

const auth = {
  isSistema: true,
  currentBranchId: null as string | null,
  permisos: new Set(['pos:acceder', 'usuarios:listar']),
  roles: new Set(['AdministradorSistema']),
  hasPermission: (p: string) => auth.permisos.has(p),
  hasRole: (r: string) => auth.roles.has(r),
}

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/stores/alertasInventario', () => ({
  useAlertasInventarioStore: () => ({ totalAlertas: 0 }),
}))
vi.mock('@/stores/shellIndicadores', () => ({
  useShellIndicadoresStore: () => ({ comandasPendientes: 0, ninosActivos: 0 }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ resolve: () => ({ path: '/' }) }) }))

const { useAppNavigation } = await import('@/composables/useAppNavigation')

function rutasVisibles(): string[] {
  return useAppNavigation()
    .visibleGroups.value.flatMap((g) => g.items)
    .map((i) => i.routeName)
}

beforeEach(() => {
  auth.isSistema = true
  auth.currentBranchId = null
  auth.roles = new Set(['AdministradorSistema'])
})

describe('menú lateral', () => {
  it('AdministradorSistema sin sucursal no ve la caja', () => {
    const rutas = rutasVisibles()
    expect(rutas).not.toContain('pos-caja')
    expect(rutas).not.toContain('pos-cierre')
    expect(rutas).toContain('usuarios-listar')
  })

  it('AdministradorSistema con una sucursal elegida sí la ve', () => {
    auth.currentBranchId = 'suc-1'
    const rutas = rutasVisibles()
    expect(rutas).toContain('pos-caja')
    expect(rutas).toContain('pos-cierre')
  })

  it('un cajero ve la caja como siempre', () => {
    auth.isSistema = false
    auth.currentBranchId = 'suc-1'
    auth.roles = new Set(['Cajero'])
    const rutas = rutasVisibles()
    expect(rutas).toContain('pos-caja')
    expect(rutas).toContain('pos-cierre')
  })
})
