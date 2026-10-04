import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useCancelarComanda } from '../useCancelarComanda'
import { cancelarComanda, devolverComanda } from '@/services/comandaService'
import { turnoParaAutorizacion } from '@/utils/autorizacionAdmin'
import type { ApiError } from '@/types/auth'

vi.mock('@/services/comandaService', () => ({
  cancelarComanda: vi.fn(),
  devolverComanda: vi.fn(),
}))
vi.mock('@/components/historial/AutorizacionAdminDialog.vue', () => ({ default: {} }))

// Resultado que "elige" el usuario en el diálogo del PIN: un token o desistir.
let respuestaDialogo: { token: string } | 'cancelar' = 'cancelar'
const dialog = vi.fn(() => {
  const encadenado = {
    onOk(fn: (token: string) => void) {
      if (respuestaDialogo !== 'cancelar') fn(respuestaDialogo.token)
      return encadenado
    },
    onCancel(fn: () => void) {
      if (respuestaDialogo === 'cancelar') fn()
      return encadenado
    },
  }
  return encadenado
})
vi.mock('quasar', () => ({ useQuasar: () => ({ dialog }) }))

const mockCancelar = vi.mocked(cancelarComanda)
const mockDevolver = vi.mocked(devolverComanda)

const requiereAutorizacion: ApiError = {
  statusCode: 403,
  code: 'AUTORIZACION_ADMIN_REQUERIDA',
  message: 'La orden ya está pagada: cancelarla requiere la autorización con PIN.',
  details: { code: 'AUTORIZACION_ADMIN_REQUERIDA', turno_id: 'turno-1' },
}

describe('turnoParaAutorizacion', () => {
  it('extrae el turno del 403 de autorización', () => {
    expect(turnoParaAutorizacion(requiereAutorizacion)).toBe('turno-1')
  })

  it('ignora cualquier otro error', () => {
    expect(turnoParaAutorizacion({ ...requiereAutorizacion, code: 'TURNO_NO_ABIERTO' })).toBe(null)
    expect(turnoParaAutorizacion({ ...requiereAutorizacion, details: undefined })).toBe(null)
    expect(turnoParaAutorizacion(new Error('x'))).toBe(null)
    expect(turnoParaAutorizacion(null)).toBe(null)
  })
})

describe('useCancelarComanda', () => {
  beforeEach(() => {
    mockCancelar.mockReset()
    dialog.mockClear()
    respuestaDialogo = 'cancelar'
  })

  it('cancela sin pedir PIN cuando la orden no está pagada', async () => {
    mockCancelar.mockResolvedValueOnce()
    const { cancelarComanda: cancelar } = useCancelarComanda()

    await expect(cancelar('c1', 'Otro')).resolves.toBe(true)
    expect(mockCancelar).toHaveBeenCalledWith('c1', 'Otro')
    expect(dialog).not.toHaveBeenCalled()
  })

  it('pide el PIN del administrador y reintenta con el token', async () => {
    mockCancelar.mockRejectedValueOnce(requiereAutorizacion).mockResolvedValueOnce()
    respuestaDialogo = { token: 'tok-123' }
    const { cancelarComanda: cancelar } = useCancelarComanda()

    await expect(cancelar('c1', 'Otro')).resolves.toBe(true)
    expect(dialog).toHaveBeenCalledWith(
      expect.objectContaining({
        componentProps: { turnoId: 'turno-1', mensaje: requiereAutorizacion.message },
      }),
    )
    expect(mockCancelar).toHaveBeenLastCalledWith('c1', 'Otro', 'tok-123')
  })

  it('no cancela si el usuario cierra el diálogo del PIN', async () => {
    mockCancelar.mockRejectedValueOnce(requiereAutorizacion)
    const { cancelarComanda: cancelar } = useCancelarComanda()

    await expect(cancelar('c1', 'Otro')).resolves.toBe(false)
    expect(mockCancelar).toHaveBeenCalledTimes(1)
  })

  it('relanza los demás errores del servidor para mostrarlos', async () => {
    const turnoCerrado: ApiError = {
      statusCode: 409,
      code: 'VENTA_DE_TURNO_CERRADO',
      message: 'La orden se cobró en un turno de caja que ya se cerró.',
    }
    mockCancelar.mockRejectedValueOnce(turnoCerrado)
    const { cancelarComanda: cancelar } = useCancelarComanda()

    await expect(cancelar('c1', 'Otro')).rejects.toBe(turnoCerrado)
    expect(dialog).not.toHaveBeenCalled()
  })
})

describe('useCancelarComanda().devolverComanda (A4: orden entregada)', () => {
  beforeEach(() => {
    mockDevolver.mockReset()
    dialog.mockClear()
    respuestaDialogo = 'cancelar'
  })

  it('pide el PIN con los textos de la devolución y reintenta con el token', async () => {
    mockDevolver.mockRejectedValueOnce(requiereAutorizacion).mockResolvedValueOnce()
    respuestaDialogo = { token: 'tok-9' }
    const { devolverComanda: devolver } = useCancelarComanda()

    await expect(devolver('c1', 'Pedido equivocado')).resolves.toBe(true)
    expect(mockDevolver).toHaveBeenNthCalledWith(1, 'c1', 'Pedido equivocado', undefined)
    expect(mockDevolver).toHaveBeenLastCalledWith('c1', 'Pedido equivocado', 'tok-9')
    expect(dialog).toHaveBeenCalledWith(
      expect.objectContaining({
        componentProps: expect.objectContaining({
          turnoId: 'turno-1',
          botonLabel: 'Autorizar devolución',
          aviso: expect.stringContaining('no regresa al inventario'),
        }),
      }),
    )
  })

  it('no devuelve si el usuario cierra el diálogo del PIN', async () => {
    mockDevolver.mockRejectedValueOnce(requiereAutorizacion)
    const { devolverComanda: devolver } = useCancelarComanda()

    await expect(devolver('c1', 'Otro')).resolves.toBe(false)
    expect(mockDevolver).toHaveBeenCalledTimes(1)
  })

  it('relanza los demás errores (p. ej. ya devuelta)', async () => {
    const yaDevuelta: ApiError = {
      statusCode: 409,
      code: 'DEVOLUCION_NO_APLICA',
      message: 'La orden ya está cancelada o devuelta; no se puede devolver otra vez.',
    }
    mockDevolver.mockRejectedValueOnce(yaDevuelta)
    const { devolverComanda: devolver } = useCancelarComanda()

    await expect(devolver('c1', 'Otro')).rejects.toBe(yaDevuelta)
    expect(dialog).not.toHaveBeenCalled()
  })
})
