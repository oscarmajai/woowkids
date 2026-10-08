import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import HorariosPage from '@/pages/admin/HorariosPage.vue'
import type { Horario } from '@/types/horario'

/**
 * Los horarios son por sucursal. El Administrador de sucursal crea y
 * edita los suyos; los globales (sucursalId null) solo el AdministradorSistema.
 */

const auth = vi.hoisted(() => ({
  isSistema: false,
  currentBranchId: 'suc-1' as string | null,
  hasPermission: () => true,
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/services/horarioService', () => ({
  horarioService: {
    listHorarios: vi.fn(async (): Promise<Horario[]> => [
      {
        id: 'h-global',
        nombre: 'Matutino general',
        horaInicio: '08:00',
        horaFin: '14:00',
        activo: true,
        dias: null,
        sucursalId: null,
      },
      {
        id: 'h-suc',
        nombre: 'Vespertino propio',
        horaInicio: '14:00',
        horaFin: '20:00',
        activo: true,
        dias: null,
        sucursalId: 'suc-1',
      },
    ]),
  },
}))

const montar = () =>
  mount(HorariosPage, {
    global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
  })

const botones = (wrapper: ReturnType<typeof montar>, etiqueta: string) =>
  wrapper.findAll('button').filter((b) => b.attributes('aria-label') === etiqueta)

describe('HorariosPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    auth.isSistema = false
    auth.currentBranchId = 'suc-1'
  })

  it('el Administrador crea horarios y solo edita los de su sucursal', async () => {
    const wrapper = montar()
    await flushPromises()

    expect(wrapper.text()).toContain('Nuevo horario')
    expect(wrapper.text()).toContain('Todas las sucursales')
    expect(botones(wrapper, 'Editar')).toHaveLength(1)
    expect(botones(wrapper, 'Desactivar')).toHaveLength(1)
  })

  it('el AdministradorSistema también edita los globales', async () => {
    auth.isSistema = true
    auth.currentBranchId = null
    const wrapper = montar()
    await flushPromises()

    expect(botones(wrapper, 'Editar')).toHaveLength(2)
    expect(botones(wrapper, 'Desactivar')).toHaveLength(2)
  })
})
