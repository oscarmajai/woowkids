import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

/**
 * El aviso de privacidad integral es público: lo abre el tutor desde el QR o
 * el enlace del aviso simplificado, sin sesión de personal.
 */

const auth = {
  isAuthenticated: false,
  currentUser: null as { id: string; debeCambiarPassword?: boolean } | null,
  isSistema: false,
  currentBranchId: null as string | null,
  hasPermission: () => false,
  hasRole: () => false,
  tryRefresh: vi.fn(async () => false),
}

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/stores/turnoCaja', () => ({ useTurnoCajaStore: () => ({}) }))
vi.mock('@/stores/accessControl', () => ({ useAccessControlStore: () => ({}) }))

const { setupRouterGuards } = await import('@/router/guards')
const { default: appRouter } = await import('@/router')

beforeEach(() => {
  auth.isAuthenticated = false
  auth.currentUser = null
  auth.tryRefresh.mockClear()
})

describe('ruta /aviso-de-privacidad', () => {
  it('existe, no pide sesión y no usa el layout de la app', () => {
    const ruta = appRouter.resolve('/aviso-de-privacidad')

    expect(ruta.name).toBe('aviso-privacidad')
    expect(ruta.meta.requiresAuth).toBeFalsy()
    expect(ruta.meta.permissions).toBeUndefined()
    expect(ruta.matched).toHaveLength(2) // PublicLayout + AvisoPrivacidadPage
  })

  it('sin sesión el guard deja entrar (no manda al login ni intenta refrescar)', async () => {
    const meta = appRouter.resolve('/aviso-de-privacidad').meta
    const Vacio = { template: '<div />' }
    const rutas: RouteRecordRaw[] = [
      { path: '/login', name: 'login', component: Vacio, meta: { publicOnly: true } },
      { path: '/aviso-de-privacidad', name: 'aviso-privacidad', component: Vacio, meta },
    ]
    const router = createRouter({ history: createMemoryHistory(), routes: rutas })
    setupRouterGuards(router)

    await router.push('/aviso-de-privacidad')

    expect(router.currentRoute.value.name).toBe('aviso-privacidad')
    expect(auth.tryRefresh).not.toHaveBeenCalled()
  })
})
