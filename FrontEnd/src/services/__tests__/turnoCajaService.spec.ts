import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { ApiError } from '@/types/auth'

vi.mock('@/api/turnoCajaApi', () => ({
  turnoCajaApi: {
    abrirTurno: vi.fn(),
    autenticarRevisionAdmin: vi.fn(),
    validarPinAdmin: vi.fn(),
  },
}))

import { turnoCajaApi } from '@/api/turnoCajaApi'
import { turnoCajaService, CredencialesAdminInvalidasError } from '@/services/turnoCajaService'

const api = vi.mocked(turnoCajaApi)

function apiError(statusCode: number, code: string, message: string): ApiError {
  return { statusCode, code, message } as ApiError
}

const REVISION = { turnoId: 't1', adminEmail: 'admin@x.mx', adminPassword: 'x' }

describe('turnoCajaService — errores de PIN (A5/A16)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it.each([
    apiError(403, 'CREDENCIALES_INVALIDAS', 'Contraseña o PIN incorrecto.'),
    apiError(403, 'PIN_INVALIDO', 'El PIN ingresado es incorrecto.'),
    apiError(401, 'CREDENCIALES_INVALIDAS', 'Contraseña o PIN incorrecto.'),
  ])('credenciales incorrectas en la revisión → CredencialesAdminInvalidasError', async (err) => {
    api.autenticarRevisionAdmin.mockRejectedValue(err)

    await expect(turnoCajaService.autenticarAdmin(REVISION)).rejects.toBeInstanceOf(
      CredencialesAdminInvalidasError,
    )
  })

  it.each([
    apiError(
      403,
      'AUTORIZADOR_NO_VALIDO',
      'El correo no corresponde a un administrador que pueda autorizar en esta sucursal.',
    ),
    apiError(429, 'PIN_BLOQUEADO', 'Demasiados intentos fallidos de PIN.'),
    apiError(403, 'TURNO_AJENO', 'Este turno pertenece a otro cajero.'),
  ])('otros rechazos de la revisión muestran el mensaje del backend', async (err) => {
    api.autenticarRevisionAdmin.mockRejectedValue(err)

    await expect(turnoCajaService.autenticarAdmin(REVISION)).rejects.toThrow(err.message)
  })

  it('un PIN incorrecto al abrir caja muestra "PIN incorrecto"', async () => {
    api.abrirTurno.mockRejectedValue(
      apiError(403, 'PIN_INVALIDO', 'El PIN ingresado es incorrecto.'),
    )

    await expect(turnoCajaService.abrirTurno({ fondoInicial: 500, pin: '1111' })).rejects.toThrow(
      'El PIN ingresado es incorrecto.',
    )
  })

  it('el turno ya abierto en otra caja muestra el 409 del backend', async () => {
    api.abrirTurno.mockRejectedValue(
      apiError(409, 'TURNO_YA_ABIERTO', 'Ya tienes un turno abierto en CAJA 01.'),
    )

    await expect(turnoCajaService.abrirTurno({ fondoInicial: 500, pin: '1234' })).rejects.toThrow(
      'Ya tienes un turno abierto en CAJA 01.',
    )
  })
})
