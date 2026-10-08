import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import HistorialView from '@/components/historial/HistorialView.vue'
import { obtenerEstadisticas, obtenerHistorial } from '@/services/historialService'

/**
 * El historial es por sucursal: el AdministradorSistema en "Todas las
 * sucursales" no tiene una elegida, así que no se consulta y se pide elegir una.
 */

const auth = vi.hoisted(() => ({
  currentBranchId: null as string | null,
  hasPermission: () => true,
  hasRole: () => true,
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/services/historialService', () => ({
  obtenerHistorial: vi.fn(async () => []),
  obtenerEstadisticas: vi.fn(async () => ({
    total_ventas: 0,
    total_ordenes: 0,
    ticket_promedio: 0,
  })),
  exportarHistorial: vi.fn(),
}))
vi.mock('@/services/turnoCajaService', () => ({
  turnoCajaService: { obtenerCajas: vi.fn(async () => []) },
}))
vi.mock('@/stores/metodos_pago', () => ({
  useMetodosPagoStore: () => ({ metodos: [{ id: 'mp', nombre: 'Efectivo' }], cargar: vi.fn() }),
}))
vi.mock('@/composables/useCancelarComanda', () => ({
  useCancelarComanda: () => ({ cancelarComanda: vi.fn(), devolverComanda: vi.fn() }),
}))

const montar = () =>
  mount(HistorialView, {
    global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
  })

describe('HistorialView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(obtenerHistorial).mockClear()
    vi.mocked(obtenerEstadisticas).mockClear()
  })

  it('sin sucursal elegida no consulta y pide elegir una', async () => {
    auth.currentBranchId = null
    const wrapper = montar()
    await flushPromises()

    expect(obtenerHistorial).not.toHaveBeenCalled()
    expect(obtenerEstadisticas).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('elige una en el selector')
  })

  it('con sucursal elegida carga el historial', async () => {
    auth.currentBranchId = 'suc-1'
    const wrapper = montar()
    await flushPromises()

    expect(obtenerHistorial).toHaveBeenCalledTimes(1)
    expect(obtenerEstadisticas).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).not.toContain('elige una en el selector')
  })
})
