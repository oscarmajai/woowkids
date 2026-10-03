import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ActiveChild } from '@/stores/accessControl'

/**
 * B21: "Checkout" sin turno mandaba a Apertura y Cierre; un rol sin
 * pos:acceder (atención de niños) rebotaba de ahí a Inicio sin explicación.
 */

const notify = vi.fn()
const push = vi.fn()
const permisos = new Set<string>()
const setCheckoutChild = vi.fn()

vi.mock('quasar', async (original) => {
  const real = await original<typeof import('quasar')>()
  return { ...real, Notify: { ...real.Notify, create: (...a: unknown[]) => notify(...a) } }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: (p: string) => permisos.has(p) }),
}))
vi.mock('@/stores/turnoCaja', () => ({ useTurnoCajaStore: () => ({ estaOperando: false }) }))
vi.mock('@/stores/accessControl', () => ({
  useAccessControlStore: () => ({ setCheckoutChild }),
}))

const { default: ActiveChildCard } = await import('@/components/control-acceso/ActiveChildCard.vue')

const NINO = {
  registroId: 'r1',
  nombreSegundoTutor: null,
  detalleId: 'd1',
  nino: 'Valentina',
  notas: null,
  edad: 5,
  tutor: 'Laura',
  telefono: '3312345678',
  parentesco: 'Madre',
  pulsera: 'WK-0000004',
  minutosPagados: 60,
  minutosTranscurridos: 10,
  horaEntrada: '2026-10-03T07:00:00Z',
  cargoExtra: 0,
  status: 'activo',
  minutosRestantes: 50,
  progressPercent: 16,
} as unknown as ActiveChild

function montar() {
  return mount(ActiveChildCard, {
    props: { child: NINO },
    global: { stubs: { FotosRegistroDialog: true, BaseDialog: true } },
  })
}

beforeEach(() => {
  notify.mockReset()
  push.mockReset()
  permisos.clear()
})

describe('ActiveChildCard · checkout sin turno', () => {
  it('a un rol que no abre caja le explica por qué no puede', async () => {
    await montar().find('.stay__checkout').trigger('click')

    expect(push).not.toHaveBeenCalled()
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('turno de caja abierto') }),
    )
  })

  it('al cajero lo sigue mandando a Apertura y Cierre', async () => {
    permisos.add('pos:acceder')
    await montar().find('.stay__checkout').trigger('click')

    expect(push).toHaveBeenCalledWith({ name: 'pos-cierre' })
    expect(notify).not.toHaveBeenCalled()
  })
})
