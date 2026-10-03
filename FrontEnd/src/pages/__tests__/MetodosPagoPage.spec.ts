import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MetodosPagoPage from '@/pages/MetodosPagoPage.vue'
import { metodosPagoApi } from '@/api/metodosPagoApi'

/**
 * B2: en "Todas las sucursales" (AdministradorSistema sin sucursal elegida)
 * los toggles se podían pulsar y respondían 422. Ahora quedan deshabilitados
 * y se pide elegir una sucursal.
 */

const auth = vi.hoisted(() => ({
  currentBranchId: null as string | null,
  currentBranchName: null as string | null,
  hasRole: () => true,
  hasPermission: () => true,
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/api/metodosPagoApi', () => ({
  metodosPagoApi: {
    listar: vi.fn(async () => [
      {
        id: 'mp-1',
        nombre: 'Tarjeta',
        descripcion: null,
        tipo: 'T',
        comision_porcentaje: null,
        requiere_referencia: true,
        activo: true,
      },
    ]),
    activar: vi.fn(),
  },
}))

const montar = () =>
  mount(MetodosPagoPage, {
    global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
  })

const toggle = (wrapper: ReturnType<typeof montar>) => wrapper.find('[role="switch"]')

describe('MetodosPagoPage (B2)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(metodosPagoApi.activar).mockReset()
  })

  it('sin sucursal elegida deshabilita los toggles y pide elegir una', async () => {
    auth.currentBranchId = null
    const wrapper = montar()
    await flushPromises()

    expect(wrapper.text()).toContain('Elige una sucursal')
    expect(toggle(wrapper).attributes('aria-disabled')).toBe('true')
    await toggle(wrapper).trigger('click')
    expect(metodosPagoApi.activar).not.toHaveBeenCalled()
  })

  it('con sucursal elegida el toggle se puede usar', async () => {
    auth.currentBranchId = 'suc-1'
    const wrapper = montar()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Elige una sucursal')
    expect(toggle(wrapper).attributes('aria-disabled')).toBeUndefined()
  })
})
