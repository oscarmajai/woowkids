import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { computed } from 'vue'

/** Debajo de la marca no aparece "Mercurio" (nombre interno del proyecto). */

vi.mock('vue-router', () => ({
  useRoute: () => ({ name: 'home', path: '/home' }),
  useRouter: () => ({ resolve: () => ({ path: '/', href: '/' }), push: vi.fn() }),
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    isSistema: false,
    currentBranchName: 'Zapopan Plaza Patria',
    currentUser: { name: 'Sofía Ramírez', email: 's@test.local' },
    primaryRole: 'Administrador',
    hasRole: () => false,
    hasPermission: () => false,
  }),
}))
vi.mock('@/stores/sucursales', () => ({ useSucursalesStore: () => ({ activas: [] }) }))
vi.mock('@/stores/turnoCaja', () => ({ useTurnoCajaStore: () => ({ estaOperando: false }) }))
vi.mock('@/composables/useAppNavigation', () => ({
  useAppNavigation: () => ({ visibleGroups: computed(() => []), badgeFor: () => null }),
}))

const { default: AppSidebar } = await import('@/components/layout/AppSidebar.vue')

describe('AppSidebar', () => {
  it('muestra la marca sin el nombre interno "Mercurio"', () => {
    const wrapper = mount(AppSidebar, {
      global: {
        stubs: { 'router-link': true, CambiarPinDialog: true, QMenu: true },
      },
    })
    const marca = wrapper.find('.sb-brand').text()
    expect(marca).toContain('Woow Kids')
    expect(wrapper.text()).not.toContain('Mercurio')
  })
})
