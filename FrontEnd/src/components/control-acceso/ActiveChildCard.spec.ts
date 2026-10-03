import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ActiveChildCard from './ActiveChildCard.vue'
import type { ActiveChild } from '@/stores/accessControl'

vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const NINO: ActiveChild = {
  registroId: 'r1',
  nombreSegundoTutor: null,
  detalleId: 'd1',
  nino: 'Santiago Méndez',
  notas: null,
  edad: 5,
  tutor: 'Laura Méndez',
  telefono: '3311112222',
  parentesco: 'Madre',
  pulsera: 'WK-0000001',
  minutosPagados: 120,
  minutosTranscurridos: 30,
  horaEntrada: '2026-10-03T18:00:00Z',
  cargoExtra: 0,
  status: 'activo',
  minutosRestantes: 90,
  progressPercent: 25,
}

const montar = (child: ActiveChild) =>
  mount(ActiveChildCard, {
    props: { child },
    global: { stubs: { BaseDialog: true, FotosRegistroDialog: true } },
  })

describe('ActiveChildCard: notas / alergias (M26)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('muestra las notas en la tarjeta, sin abrir el detalle', () => {
    const wrapper = montar({ ...NINO, notas: 'Alérgico al cacahuate' })
    const notas = wrapper.find('.stay__notes')
    expect(notas.exists()).toBe(true)
    expect(notas.text()).toContain('Notas / alergias')
    expect(notas.text()).toContain('Alérgico al cacahuate')
  })

  it('sin notas no muestra el aviso', () => {
    expect(
      montar({ ...NINO, notas: '  ' })
        .find('.stay__notes')
        .exists(),
    ).toBe(false)
  })
})
