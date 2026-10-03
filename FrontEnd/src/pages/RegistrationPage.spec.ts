import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'

import RegistrationPage from './RegistrationPage.vue'
import { useAuthStore } from '@/stores/auth'
import { useRegistrationStore } from '@/stores/registration'
import { fetchPulseras } from '@/api/onboardingClient'
import { productosApi } from '@/api/productosApi'

vi.mock('vue-router', () => ({
  useRouter: () => ({ back: vi.fn(), push: vi.fn() }),
}))

vi.mock('@/api/onboardingClient', () => ({
  postOnboarding: vi.fn(),
  fetchActivos: vi.fn(),
  fetchPulseras: vi.fn(),
  fetchEstadoPulsera: vi.fn(),
}))

vi.mock('@/api/productosApi', () => ({
  productosApi: { obtenerPreciosEstancia: vi.fn() },
}))

// QPage exige un QLayout padre; aquí basta con un contenedor que pinte su contenido.
const QPageStub = defineComponent({
  setup(_, { slots }) {
    return () => h('div', slots.default?.())
  },
})

const STUBS = {
  QPage: QPageStub,
  TutorForm: true,
  ChildrenSection: true,
  RfidSection: true,
  OrderSummary: true,
  PrintVoucher: true,
}

function montar() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().user = {
    id: 'u1',
    name: 'Cajero',
    email: 'cajero@test.com',
    roles: ['Cajero'],
    branchId: 'suc-1',
    branchName: 'Centro',
    permissions: ['estancias:checkin'],
  }
  const wrapper = mount(RegistrationPage, { global: { plugins: [pinia], stubs: STUBS } })
  return { wrapper, store: useRegistrationStore() }
}

describe('RegistrationPage: abierta por URL o tras F5 (A14)', () => {
  beforeEach(() => {
    vi.mocked(fetchPulseras).mockReset()
    vi.mocked(productosApi.obtenerPreciosEstancia)
      .mockReset()
      .mockResolvedValue({
        id: 'prod-1',
        config_estancia: [{ min_horas: 1, max_horas: 5, precio: 100 }],
      })
  })

  it('al montarse sin estado previo carga las pulseras y las tarifas', async () => {
    vi.mocked(fetchPulseras).mockResolvedValue([
      { id: 'p1', pulseraRfid: 'WK-0000001' },
      { id: 'p2', pulseraRfid: 'WK-0000002' },
      { id: 'p3', pulseraRfid: 'WK-0000003' },
    ])
    const { wrapper, store } = montar()

    await nextTick()
    expect(wrapper.text()).toContain('Cargando tarifas y pulseras disponibles')
    await flushPromises()

    expect(fetchPulseras).toHaveBeenCalledTimes(1)
    expect(fetchPulseras).toHaveBeenCalledWith('suc-1')
    expect(productosApi.obtenerPreciosEstancia).toHaveBeenCalledTimes(1)
    expect(store.pulseras).toHaveLength(3)
    expect(store.maxChildrenAllowed).toBe(2)
    expect(wrapper.text()).not.toContain('Cargando tarifas y pulseras disponibles')
  })

  it('si no puede cargar las pulseras muestra el error y permite reintentar', async () => {
    vi.mocked(fetchPulseras)
      .mockRejectedValueOnce(Object.assign(new Error('500'), { statusCode: 500 }))
      .mockResolvedValueOnce([{ id: 'p1', pulseraRfid: 'WK-0000001' }])
    const { wrapper, store } = montar()
    await flushPromises()

    expect(wrapper.text()).toContain('No se pudo cargar la lista de pulseras disponibles.')

    const reintentar = wrapper.findAll('button').find((b) => b.text().includes('Reintentar'))
    expect(reintentar).toBeDefined()
    await reintentar!.trigger('click')
    await flushPromises()

    expect(fetchPulseras).toHaveBeenCalledTimes(2)
    expect(store.pulseras).toHaveLength(1)
    expect(wrapper.text()).not.toContain('No se pudo cargar la lista de pulseras')
  })
})
