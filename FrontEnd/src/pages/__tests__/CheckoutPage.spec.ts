import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CheckoutPage from '@/pages/CheckoutPage.vue'
import PaymentModal from '@/components/shared/payments/PaymentModal.vue'
import { checkout, cotizarCheckout } from '@/api/onboardingClient'
import { useAccessControlStore, type ActiveChild } from '@/stores/accessControl'

vi.mock('vue-router', () => ({ useRouter: () => ({ back: vi.fn(), push: vi.fn() }) }))
vi.mock('@/api/onboardingClient', () => ({ checkout: vi.fn(), cotizarCheckout: vi.fn() }))
vi.mock('@/api/metodosPagoApi', () => ({
  metodosPagoApi: {
    listar: vi.fn().mockResolvedValue([
      {
        id: 'm-efectivo',
        nombre: 'Efectivo',
        descripcion: null,
        tipo: 'E',
        comision_porcentaje: null,
        requiere_referencia: false,
        activo: true,
      },
    ]),
  },
}))

const NINO: ActiveChild = {
  registroId: 'r1',
  nombreSegundoTutor: null,
  detalleId: 'd1',
  nino: 'Mateo Ruiz',
  notas: null,
  edad: 6,
  tutor: 'Ana Ruiz',
  telefono: '3311112222',
  parentesco: 'Madre',
  pulsera: 'WK-0000008',
  minutosPagados: 60,
  minutosTranscurridos: 140,
  horaEntrada: '2026-10-03T18:00:00Z',
  cargoExtra: 100,
  status: 'excedido',
  minutosRestantes: -80,
  progressPercent: 100,
}

const COTIZACION = { detalleId: 'd1', horasExtra: 2, totalExtra: 100, cotizadoEn: 'x' }

function montar() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAccessControlStore().setCheckoutChild(NINO)
  return mount(CheckoutPage, {
    global: {
      plugins: [pinia],
      stubs: {
        QPage: { template: '<div><slot /></div>' },
        PageHeader: true,
        FotosRegistroDialog: true,
        PaymentModal: true,
      },
    },
  })
}

describe('CheckoutPage: el cargo extra se cobra antes de dar la salida', () => {
  beforeEach(() => {
    vi.mocked(cotizarCheckout).mockReset()
    vi.mocked(checkout).mockReset()
    vi.mocked(cotizarCheckout).mockResolvedValue(COTIZACION)
    vi.mocked(checkout).mockResolvedValue({
      detalleId: 'd1',
      registroId: 'r1',
      horasExtra: 2,
      totalExtra: 100,
      ninosRestantes: 0,
    })
  })

  it('con cargo extra, el botón dice que primero cobra y no da la salida sin pago', async () => {
    const wrapper = montar()
    await flushPromises()

    const confirmar = wrapper.find('.charges__confirm')
    expect(confirmar.text()).toContain('Cobrar $100.00 y dar salida')
    expect(wrapper.text()).toContain('la salida se registra al completar el cobro')
    expect(wrapper.text()).not.toContain('ya realizó checkout')

    await wrapper.find('.verify__checklist input, .verify__checklist').trigger('click')
    await flushPromises()
    await confirmar.trigger('click')
    await flushPromises()

    // Se abre el cobro, pero la salida todavía no se registró.
    expect(wrapper.findComponent(PaymentModal).props('modelValue')).toBe(true)
    expect(wrapper.findComponent(PaymentModal).props('totalToPay')).toBe(100)
    expect(checkout).not.toHaveBeenCalled()

    // Al completar el pago, salida y cargo se registran juntos.
    wrapper
      .findComponent(PaymentModal)
      .vm.$emit('pago-exitoso', [
        { id: 'p1', method: 'Efectivo', amount: 100, timestamp: new Date() },
      ])
    await flushPromises()
    expect(checkout).toHaveBeenCalledWith('d1', [
      { metodoPagoId: 'm-efectivo', monto: 100, referencia: undefined },
    ])
  })

  it('sin cargo extra, el botón confirma la salida directo', async () => {
    vi.mocked(cotizarCheckout).mockResolvedValue({ ...COTIZACION, horasExtra: 0, totalExtra: 0 })
    const wrapper = montar()
    await flushPromises()

    expect(wrapper.find('.charges__confirm').text()).toContain('Confirmar salida')
  })
})
