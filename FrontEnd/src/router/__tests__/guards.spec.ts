import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RouteLocationNormalized, Router } from 'vue-router'

import { setupRouterGuards } from '@/router/guards'

/**
 * B4: GET /turnos-caja/activo se pedía en cada página para roles que no pueden
 * consultarlo (error en consola). El guard ya no lo pide sin el permiso.
 */

const permisos = new Set<string>()
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    isAuthenticated: true,
    currentUser: { id: 'u1' },
    hasPermission: (p: string) => permisos.has(p),
    hasRole: () => false,
  }),
}))

const turno = {
  estaOperando: false,
  asegurarTurnoCargado: vi.fn().mockResolvedValue({ ok: true, hayTurno: false }),
}
vi.mock('@/stores/turnoCaja', () => ({ useTurnoCajaStore: () => turno }))
vi.mock('@/stores/accessControl', () => ({ useAccessControlStore: () => ({}) }))

type Guard = (to: RouteLocationNormalized) => unknown

function guard(): Guard {
  let registrado: Guard | null = null
  setupRouterGuards({
    beforeEach: (fn: Guard) => {
      registrado = fn
    },
  } as unknown as Router)
  return registrado!
}

const ruta = (meta: Record<string, unknown>) =>
  ({
    name: 'eventos-reservaciones-crear',
    meta,
    fullPath: '/x',
  }) as unknown as RouteLocationNormalized

beforeEach(() => {
  permisos.clear()
  vi.clearAllMocks()
})

describe('guard de turno (B4)', () => {
  it('sin turnos_caja:ver_activo no consulta el turno', async () => {
    const resultado = await guard()(ruta({ requiresTurno: true }))

    expect(turno.asegurarTurnoCargado).not.toHaveBeenCalled()
    expect(resultado).toBeUndefined()
  })

  it('con el permiso sí lo consulta y sin turno manda a abrir caja', async () => {
    permisos.add('turnos_caja:ver_activo')
    permisos.add('pos:acceder')

    const resultado = await guard()(ruta({ requiresTurno: true }))

    expect(turno.asegurarTurnoCargado).toHaveBeenCalledTimes(1)
    expect(resultado).toEqual({ name: 'pos-cierre' })
  })
})
