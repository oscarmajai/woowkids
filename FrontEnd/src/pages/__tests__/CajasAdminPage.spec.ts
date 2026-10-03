import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CajasAdminPage from '@/pages/admin/CajasAdminPage.vue'
import type { CajaAdmin } from '@/types/caja-admin'

/**
 * N14: el AdministradorSistema en "Todas las sucursales" no podía editar
 * cajas (400 SIN_SUCURSAL). Ahora ve las de todas, con su sucursal, y las
 * edita; para crear una debe elegir la sucursal.
 */

const auth = vi.hoisted(() => ({
  isSistema: true,
  currentBranchId: null as string | null,
  hasPermission: () => true,
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/services/cajaAdminService', () => ({
  cajaAdminService: {
    listCajas: vi.fn(async (): Promise<CajaAdmin[]> => [
      {
        id: 'c-1',
        nombre: 'Caja Andares',
        numero: 1,
        activo: true,
        impresora: null,
        turnoActual: null,
        sucursalId: 's-1',
        sucursalNombre: 'Andares',
      },
      {
        id: 'c-2',
        nombre: 'Caja Zapopan',
        numero: 1,
        activo: true,
        impresora: null,
        turnoActual: null,
        sucursalId: 's-2',
        sucursalNombre: 'Plaza Patria',
      },
    ]),
  },
}))

const montar = () =>
  mount(CajasAdminPage, {
    global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
  })

describe('CajasAdminPage (N14)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    auth.isSistema = true
    auth.currentBranchId = null
  })

  it('en "Todas las sucursales" muestra la sucursal de cada caja y permite editarlas', async () => {
    const wrapper = montar()
    await flushPromises()

    expect(wrapper.text()).toContain('Andares')
    expect(wrapper.text()).toContain('Plaza Patria')
    const editar = wrapper.findAll('button').filter((b) => b.attributes('aria-label') === 'Editar')
    expect(editar).toHaveLength(2)
    expect(wrapper.text()).not.toContain('Nueva caja')
  })

  it('con una sucursal elegida puede crear cajas y no repite la columna Sucursal', async () => {
    auth.currentBranchId = 's-1'
    const wrapper = montar()
    await flushPromises()

    expect(wrapper.text()).toContain('Nueva caja')
    expect(wrapper.text()).not.toContain('Plaza Patria')
  })
})
