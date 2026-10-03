import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { ApiError } from '@/types/auth'

vi.mock('@/api/turnoCajaApi', () => ({
  turnoCajaApi: {
    abrirTurno: vi.fn(),
    autenticarRevisionAdmin: vi.fn(),
    validarPinAdmin: vi.fn(),
    registrarRetiro: vi.fn(),
    registrarIngreso: vi.fn(),
    obtenerActivo: vi.fn(),
  },
}))

import { turnoCajaApi } from '@/api/turnoCajaApi'
import {
  turnoCajaService,
  CredencialesAdminInvalidasError,
  TurnoNoEncontradoError,
} from '@/services/turnoCajaService'

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

describe('turnoCajaService — retiros e ingresos rechazados (B17)', () => {
  const RETIRO = {
    turnoId: 't1',
    concepto: 'Gastos varios' as const,
    tipoDestinatario: 'Empleado' as const,
    monto: 6000,
  }

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('un retiro mayor al disponible muestra el mensaje del backend con el monto', async () => {
    const mensaje = 'El retiro excede el efectivo disponible en caja (disponible: $6,040.00).'
    api.registrarRetiro.mockRejectedValue(apiError(409, 'EFECTIVO_INSUFICIENTE', mensaje))

    await expect(turnoCajaService.registrarRetiro(RETIRO)).rejects.toThrow(mensaje)
  })

  it('un 409 sin mensaje conserva el texto genérico', async () => {
    api.registrarRetiro.mockRejectedValue(apiError(409, 'TRANSICION_INVALIDA', ''))

    await expect(turnoCajaService.registrarRetiro(RETIRO)).rejects.toThrow(
      'No se pueden registrar retiros en este momento.',
    )
  })

  it('un ingreso rechazado muestra el mensaje del backend', async () => {
    const mensaje =
      'No se pueden registrar ingresos de efectivo mientras el turno está en conteo o cierre.'
    api.registrarIngreso.mockRejectedValue(apiError(409, 'TRANSICION_INVALIDA', mensaje))

    await expect(turnoCajaService.registrarIngreso({ turnoId: 't1', monto: 100 })).rejects.toThrow(
      mensaje,
    )
  })
})

describe('turnoCajaService — turno activo sin turno (B4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('un null del backend (opcional=true) es "no hay turno", sin 404', async () => {
    api.obtenerActivo.mockResolvedValue(null)

    await expect(turnoCajaService.cargarTurnoActivo()).rejects.toBeInstanceOf(
      TurnoNoEncontradoError,
    )
  })

  it('un 404 de un backend viejo también es "no hay turno"', async () => {
    api.obtenerActivo.mockRejectedValue(apiError(404, 'TURNO_NO_ENCONTRADO', 'No hay turno.'))

    await expect(turnoCajaService.cargarTurnoActivo()).rejects.toBeInstanceOf(
      TurnoNoEncontradoError,
    )
  })
})
