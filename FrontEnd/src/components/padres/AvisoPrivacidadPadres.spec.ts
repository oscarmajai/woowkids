import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import AvisoPrivacidadPadres from './AvisoPrivacidadPadres.vue'
import { useAvisoPrivacidadStore } from '@/stores/avisoPrivacidad'
import type { AvisoPrivacidad } from '@/types/privacidad'

const AVISO: AvisoPrivacidad = {
  version: 4,
  vigenteDesde: '2026-10-01T00:00:00Z',
  fechaVigencia: '2026-10-01',
  nombreComercial: 'Woow Kids',
  textoIntegral: '# Aviso integral',
  textoSimplificado: '# Aviso simplificado\n\nUsamos los datos de tu hijo para su estancia.',
}

let pinia: Pinia

function montar(abierto = true) {
  return mount(AvisoPrivacidadPadres, { props: { abierto }, global: { plugins: [pinia] } })
}

describe('AvisoPrivacidadPadres', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
  })

  it('muestra el aviso simplificado y la versión vigente', async () => {
    const store = useAvisoPrivacidadStore()
    store.vigente = AVISO
    vi.spyOn(store, 'cargarVigente').mockResolvedValue()
    const wrapper = montar()
    await flushPromises()

    expect(wrapper.text()).toContain('Aviso de privacidad')
    expect(wrapper.text()).toContain('Versión 4')
    expect(wrapper.text()).toContain('Usamos los datos de tu hijo para su estancia.')
  })

  it('enlaza el aviso integral en otra pestaña, sin sacar al tutor de su sesión', async () => {
    const store = useAvisoPrivacidadStore()
    store.vigente = AVISO
    vi.spyOn(store, 'cargarVigente').mockResolvedValue()
    const enlace = montar().get('a.aviso-padres__integral')

    expect(enlace.attributes('href')).toBe('/aviso-de-privacidad')
    expect(enlace.attributes('target')).toBe('_blank')
    expect(enlace.attributes('rel')).toContain('noopener')
  })

  it('pide el aviso al montarse si todavía no está cargado', async () => {
    const store = useAvisoPrivacidadStore()
    const cargar = vi.spyOn(store, 'cargarVigente').mockResolvedValue()
    montar()
    await flushPromises()
    expect(cargar).toHaveBeenCalledOnce()
  })

  it('no vuelve a pedirlo si ya lo tiene', async () => {
    const store = useAvisoPrivacidadStore()
    store.vigente = AVISO
    const cargar = vi.spyOn(store, 'cargarVigente').mockResolvedValue()
    montar()
    await flushPromises()
    expect(cargar).not.toHaveBeenCalled()
  })

  it('si falla la carga muestra el error y deja reintentar; el integral sigue disponible', async () => {
    const store = useAvisoPrivacidadStore()
    store.errorVigente = 'Sin conexión'
    vi.spyOn(store, 'cargarVigente').mockResolvedValue()
    const wrapper = montar()
    await flushPromises()

    expect(wrapper.text()).toContain('Sin conexión')
    expect(wrapper.text()).toContain('Reintentar')
    expect(wrapper.find('a.aviso-padres__integral').exists()).toBe(true)
  })
})
