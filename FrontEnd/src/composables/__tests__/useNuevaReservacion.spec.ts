import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useNuevaReservacion } from '@/composables/useNuevaReservacion'

/**
 * M10: el asistente decía al Administrador "Tu rol no opera caja" aunque desde
 * la migración 073 abre y cierra su propio turno (y el guard lo deja entrar a
 * /pos/cierre). Ahora decide por el permiso de abrir caja, no por el rol.
 */

const push = vi.fn()
const notify = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))
vi.mock('quasar', async (original) => ({
  ...(await original<typeof import('quasar')>()),
  useQuasar: () => ({ notify }),
}))

const permisos = new Set<string>()
const roles = new Set<string>()
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    hasPermission: (p: string) => permisos.has(p),
    hasRole: (r: string) => roles.has(r),
  }),
}))

const turno = { estaOperando: false }
vi.mock('@/stores/turnoCaja', () => ({ useTurnoCajaStore: () => turno }))

beforeEach(() => {
  vi.clearAllMocks()
  permisos.clear()
  roles.clear()
  turno.estaOperando = false
})

describe('useNuevaReservacion', () => {
  it('con turno abierto va directo al asistente', () => {
    turno.estaOperando = true

    useNuevaReservacion()()

    expect(push).toHaveBeenCalledWith({ name: 'eventos-reservaciones-crear' })
  })

  it('el Administrador sin turno va a abrir su caja (no "tu rol no opera caja")', () => {
    roles.add('Administrador')
    permisos.add('turnos_caja:abrir')

    useNuevaReservacion()()

    expect(push).toHaveBeenCalledWith({ name: 'pos-cierre' })
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Abre tu caja para poder registrar el anticipo de la reservación.',
      }),
    )
  })

  it('un rol que no abre caja recibe la explicación y no se navega', () => {
    useNuevaReservacion()()

    expect(push).not.toHaveBeenCalled()
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        caption: 'Tu rol no opera caja: pide a un cajero que abra su turno.',
      }),
    )
  })
})
