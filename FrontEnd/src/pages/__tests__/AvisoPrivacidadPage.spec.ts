import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import AvisoPrivacidadPage from '@/pages/AvisoPrivacidadPage.vue'
import { privacidadService } from '@/services/privacidadService'

vi.mock('@/services/privacidadService', () => ({
  privacidadService: { obtenerVigente: vi.fn() },
}))

const QPageStub = defineComponent({
  setup(_, { slots }) {
    return () => h('div', slots.default?.())
  },
})

function montar() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return mount(AvisoPrivacidadPage, { global: { plugins: [pinia], stubs: { QPage: QPageStub } } })
}

describe('AvisoPrivacidadPage', () => {
  beforeEach(() => {
    vi.mocked(privacidadService.obtenerVigente).mockReset()
  })

  it('muestra el aviso integral vigente con su formato', async () => {
    vi.mocked(privacidadService.obtenerVigente).mockResolvedValue({
      version: 1,
      vigenteDesde: '2026-10-03T18:00:00Z',
      fechaVigencia: '2026-10-03',
      nombreComercial: 'Woow Kids Centro',
      textoIntegral: '# AVISO DE PRIVACIDAD INTEGRAL\n\n## 1. Responsable\n\n- Nombre\n- Teléfono',
      textoSimplificado: 'Simplificado',
    })

    const wrapper = montar()
    await flushPromises()

    expect(wrapper.find('h1').text()).toBe('AVISO DE PRIVACIDAD INTEGRAL')
    expect(wrapper.find('h2').text()).toBe('1. Responsable')
    expect(wrapper.findAll('li').map((li) => li.text())).toEqual(['Nombre', 'Teléfono'])
    expect(wrapper.text()).toContain('Woow Kids Centro')
    expect(wrapper.text()).toContain('Imprimir')
    expect(wrapper.text()).not.toContain('Simplificado')
  })

  it('si no carga, lo dice y permite reintentar', async () => {
    vi.mocked(privacidadService.obtenerVigente).mockRejectedValue({
      statusCode: 0,
      code: 'NETWORK_ERROR',
      message: 'Sin conexión a internet. Verifica tu red.',
    })

    const wrapper = montar()
    await flushPromises()

    expect(wrapper.text()).toContain('No se pudo cargar el aviso de privacidad')
    expect(wrapper.text()).toContain('Sin conexión a internet')
  })
})
