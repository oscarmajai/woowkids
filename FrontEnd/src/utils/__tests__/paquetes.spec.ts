import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { diferenciaTipos, paqueteSirveParaTipo } from '@/utils/paquetes'
import { usePaquetesTipoEventoStore } from '@/stores/paquetes_tipo_evento'
import { paquetesTipoEventoApi } from '@/api/paquetesTipoEventoApi'

vi.mock('@/api/paquetesTipoEventoApi', () => ({
  paquetesTipoEventoApi: {
    listar: vi.fn(),
    crear: vi.fn((body: { paquete_id: string; tipo_evento_id: string }) => Promise.resolve(body)),
    eliminar: vi.fn(() => Promise.resolve()),
  },
}))

/**
 * No había forma en la UI de asignar tipos de evento a un paquete, y Nueva
 * reservación ofrecía todos los paquetes para cualquier tipo.
 */
describe('paqueteSirveParaTipo', () => {
  const cumple = { id: 'cumple', nombre: 'Cumpleaños' }
  const bautizo = { id: 'bautizo', nombre: 'Bautizo' }

  it('ofrece el paquete solo para sus tipos de evento', () => {
    const paquete = { tipos_evento: [cumple] }
    expect(paqueteSirveParaTipo(paquete, 'cumple')).toBe(true)
    expect(paqueteSirveParaTipo(paquete, 'bautizo')).toBe(false)
  })

  it('un paquete sin tipos asignados sirve para todos', () => {
    expect(paqueteSirveParaTipo({ tipos_evento: [] }, 'bautizo')).toBe(true)
  })

  it('sin tipo de evento elegido no descarta ningún paquete', () => {
    expect(paqueteSirveParaTipo({ tipos_evento: [bautizo] }, null)).toBe(true)
  })
})

describe('diferenciaTipos', () => {
  it('calcula qué tipos asociar y cuáles quitar', () => {
    expect(diferenciaTipos(['a', 'b'], ['b', 'c'])).toEqual({ agregar: ['c'], quitar: ['a'] })
    expect(diferenciaTipos([], [])).toEqual({ agregar: [], quitar: [] })
  })
})

describe('usePaquetesTipoEventoStore.sincronizar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('asocia los tipos nuevos y desasocia los que se quitaron', async () => {
    await usePaquetesTipoEventoStore().sincronizar('paq-1', ['cumple', 'bautizo'], ['cumple', 'xv'])
    expect(paquetesTipoEventoApi.crear).toHaveBeenCalledTimes(1)
    expect(paquetesTipoEventoApi.crear).toHaveBeenCalledWith({
      paquete_id: 'paq-1',
      tipo_evento_id: 'xv',
    })
    expect(paquetesTipoEventoApi.eliminar).toHaveBeenCalledTimes(1)
    expect(paquetesTipoEventoApi.eliminar).toHaveBeenCalledWith('paq-1', 'bautizo')
  })

  it('sin cambios no llama a la API', async () => {
    await usePaquetesTipoEventoStore().sincronizar('paq-1', ['cumple'], ['cumple'])
    expect(paquetesTipoEventoApi.crear).not.toHaveBeenCalled()
    expect(paquetesTipoEventoApi.eliminar).not.toHaveBeenCalled()
  })
})
