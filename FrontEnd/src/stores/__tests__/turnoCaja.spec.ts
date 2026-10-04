import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useTurnoCajaStore } from '@/stores/turnoCaja'
import { turnoCajaService, TurnoNoEncontradoError } from '@/services/turnoCajaService'
import type { TurnoActivoResponse } from '@/types/turnoCaja'

vi.mock('@/services/turnoCajaService', () => {
  class TurnoNoEncontradoError extends Error {
    constructor() {
      super('No se encontró un turno activo para esta sesión.')
      this.name = 'TurnoNoEncontradoError'
    }
  }
  return {
    TurnoNoEncontradoError,
    turnoCajaService: {
      abrirTurno: vi.fn(),
      cargarTurnoActivo: vi.fn(),
      iniciarConteo: vi.fn(),
      enviarConteo: vi.fn(),
      autenticarAdmin: vi.fn(),
      cancelarConteo: vi.fn(),
      registrarRetiro: vi.fn(),
      confirmarCierre: vi.fn(),
    },
  }
})

const servicio = vi.mocked(turnoCajaService)

function turnoEn(
  estado: TurnoActivoResponse['estado'],
  extra: Partial<TurnoActivoResponse> = {},
): TurnoActivoResponse {
  return {
    id: 'turno-1',
    sucursalId: 'suc-1',
    sucursalNombre: 'Centro',
    cajeroId: 'cajero-1',
    cajeroNombre: 'Ana',
    terminal: 'CAJA 01',
    estado,
    fondoInicial: 1000,
    fechaApertura: '2026-01-01T10:00:00Z',
    totalVentas: 0,
    totalRetiros: 0,
    totalIngresos: 0,
    numeroVentas: 0,
    totalVendido: 0,
    movimientos: [],
    ...extra,
  }
}

beforeEach(() => {
  sessionStorage.clear()
  setActivePinia(createPinia())
  vi.resetAllMocks()
})

describe('confirmarCierre', () => {
  it('devuelve ok:false y no cambia el estado cuando el backend falla', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(turnoEn('BALANCE_REVELADO'))
    await store.cargarTurnoActivo()
    servicio.confirmarCierre.mockRejectedValue(new Error('Error interno del servidor.'))

    const resultado = await store.confirmarCierre('obs')

    expect(resultado).toEqual({ ok: false, error: 'Error interno del servidor.' })
    expect(store.estado).toBe('BALANCE_REVELADO')
    expect(store.turnoId).toBe('turno-1')
    expect(store.error).toBe('Error interno del servidor.')
  })

  it('devuelve arqueoId y pdfUrl cuando el cierre sale bien', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(turnoEn('BALANCE_REVELADO'))
    await store.cargarTurnoActivo()
    servicio.confirmarCierre.mockResolvedValue({
      arqueoId: 'arq-9',
      estado: 'CERRADO',
      pdfUrl: '/x.pdf',
      mensaje: 'ok',
    })

    const resultado = await store.confirmarCierre('obs')

    expect(resultado).toEqual({ ok: true, pdfUrl: '/x.pdf', arqueoId: 'arq-9' })
    expect(store.estado).toBe('CERRADO')
  })
})

describe('cargarTurnoActivo', () => {
  it('con 404 pasa a SIN_TURNO y reporta que no hay turno', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValueOnce(turnoEn('OPERANDO'))
    await store.cargarTurnoActivo()
    servicio.cargarTurnoActivo.mockRejectedValueOnce(new TurnoNoEncontradoError())

    const resultado = await store.cargarTurnoActivo()

    expect(resultado).toEqual({ ok: true, hayTurno: false })
    expect(store.estado).toBe('SIN_TURNO')
    expect(store.turnoId).toBeNull()
    expect(store.error).toBeNull()
  })

  it('con un error 500 conserva el turno, asigna error y reporta el fallo', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValueOnce(turnoEn('OPERANDO'))
    await store.cargarTurnoActivo()
    servicio.cargarTurnoActivo.mockRejectedValueOnce(new Error('Error interno del servidor.'))

    const resultado = await store.cargarTurnoActivo()

    expect(resultado).toEqual({ ok: false, error: 'Error interno del servidor.' })
    expect(store.estado).toBe('OPERANDO')
    expect(store.turnoId).toBe('turno-1')
    expect(store.error).toBe('Error interno del servidor.')
  })
})

describe('asegurarTurnoCargado', () => {
  it('comparte una sola peticion entre llamadas concurrentes', async () => {
    const store = useTurnoCajaStore()
    let resolver!: (v: TurnoActivoResponse) => void
    servicio.cargarTurnoActivo.mockReturnValue(
      new Promise((resolve) => {
        resolver = resolve
      }),
    )

    const p1 = store.asegurarTurnoCargado()
    const p2 = store.asegurarTurnoCargado()
    resolver(turnoEn('OPERANDO'))
    const [r1, r2] = await Promise.all([p1, p2])

    expect(servicio.cargarTurnoActivo).toHaveBeenCalledTimes(1)
    expect(r1).toEqual({ ok: true, hayTurno: true })
    expect(r2).toEqual({ ok: true, hayTurno: true })
  })

  it('no vuelve a pedir el turno si ya se cargo para la sucursal vigente', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(turnoEn('OPERANDO'))

    await store.asegurarTurnoCargado()
    await store.asegurarTurnoCargado()

    expect(servicio.cargarTurnoActivo).toHaveBeenCalledTimes(1)
  })

  it('no memoiza una carga fallida: la siguiente llamada reintenta', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockRejectedValueOnce(new Error('Error interno del servidor.'))
    servicio.cargarTurnoActivo.mockResolvedValueOnce(turnoEn('OPERANDO'))

    const primero = await store.asegurarTurnoCargado()
    const segundo = await store.asegurarTurnoCargado()

    expect(primero).toEqual({ ok: false, error: 'Error interno del servidor.' })
    expect(segundo).toEqual({ ok: true, hayTurno: true })
    expect(servicio.cargarTurnoActivo).toHaveBeenCalledTimes(2)
  })
})

describe('enviarConteo', () => {
  async function storeEnConteo() {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValueOnce(turnoEn('EN_CONTEO'))
    await store.cargarTurnoActivo()
    store.totalContadoDeclarado = 500
    return store
  }

  it('ante TRANSICION_INVALIDA resincroniza el turno y abre el modal del admin sin error', async () => {
    const store = await storeEnConteo()
    servicio.enviarConteo.mockRejectedValue(
      new Error('transicion invalida', {
        cause: { code: 'TRANSICION_INVALIDA', statusCode: 409, message: 'x' },
      }),
    )
    servicio.cargarTurnoActivo.mockResolvedValueOnce(turnoEn('ESPERANDO_REVISION'))

    await store.enviarConteo()

    expect(store.estado).toBe('ESPERANDO_REVISION')
    expect(store.mostrarDialogAdmin).toBe(true)
    expect(store.error).toBeNull()
  })

  it('ante otro error muestra el mensaje y no resincroniza', async () => {
    const store = await storeEnConteo()
    servicio.enviarConteo.mockRejectedValue(
      new Error('boom', { cause: { code: 'X', statusCode: 500, message: 'boom' } }),
    )
    servicio.cargarTurnoActivo.mockClear()

    await store.enviarConteo()

    expect(servicio.cargarTurnoActivo).not.toHaveBeenCalled()
    expect(store.error).toBe('boom')
  })
})

describe('turno en BALANCE_REVELADO tras recargar', () => {
  it('abre la re-autenticacion del admin y recupera su email desde sessionStorage', async () => {
    sessionStorage.setItem(
      'mercury:turnoCaja:adminEmail',
      JSON.stringify({ turnoId: 'turno-1', email: 'admin@x.com' }),
    )
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(turnoEn('BALANCE_REVELADO'))

    await store.cargarTurnoActivo()

    expect(store.balanceRevelado).toBe(true)
    expect(store.mostrarDialogAdmin).toBe(true)
    expect(store.adminEmail).toBe('admin@x.com')
  })

  it('tras re-autenticar al admin abre la autorizacion con el balance', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(turnoEn('BALANCE_REVELADO'))
    await store.cargarTurnoActivo()
    servicio.autenticarAdmin.mockResolvedValue({
      autorizado: true,
      adminNombre: 'Admin',
      totalEsperado: 100,
      totalDeclarado: 90,
      diferenciaNeta: -10,
      balancePorMetodo: [],
    })
    store.credencialesAdmin.email = 'admin@x.com'
    store.credencialesAdmin.password = 'pw'

    expect(await store.autenticarAdmin()).toBe(true)

    expect(store.mostrarDialogAdmin).toBe(false)
    expect(store.mostrarDialogAutorizacion).toBe(true)
    expect(store.adminEmail).toBe('admin@x.com')
  })

  it('usa adminEmail y balancePorMetodo del backend sin re-autenticar (QA #8)', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(
      turnoEn('BALANCE_REVELADO', {
        adminEmail: 'admin-backend@x.com',
        balancePorMetodo: [
          {
            metodo: 'efectivo',
            label: 'Efectivo en Caja',
            declarado: 100,
            esperado: 100,
            diferencia: 0,
            devoluciones: 0,
          },
        ],
      }),
    )

    await store.cargarTurnoActivo()

    expect(store.adminEmail).toBe('admin-backend@x.com')
    expect(store.balancePorMetodo).toHaveLength(1)
    expect(store.mostrarDialogAdmin).toBe(false)
    expect(store.mostrarDialogAutorizacion).toBe(true)
    expect(servicio.autenticarAdmin).not.toHaveBeenCalled()
  })
})

describe('filas de metodos de pago', () => {
  it('usan ids unicos entre filas de sistema y manuales', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(
      turnoEn('OPERANDO', {
        movimientos: [
          { metodo: 'Tarjeta', totalVentas: 100 },
          { metodo: 'Transferencia', totalVentas: 50 },
        ],
      }),
    )
    await store.cargarTurnoActivo()
    store.metodosPago.push({
      id: crypto.randomUUID(),
      metodo: 'Vales',
      monto: null,
      origen: 'manual',
    })
    // una recarga conserva la fila manual y regenera las de sistema
    await store.cargarTurnoActivo()

    const ids = store.metodosPago.map((f) => f.id)
    expect(ids).toHaveLength(3)
    expect(new Set(ids).size).toBe(3)
    expect(ids.every((id) => typeof id === 'string')).toBe(true)
  })
})

describe('B23: recargar con el conteo en espera de revisión', () => {
  const conteoGuardado = {
    desgloseEfectivo: {
      billetes: [
        { denominacion: 500, cantidad: 7 },
        { denominacion: 20, cantidad: 2 },
      ],
      monedas: [
        { denominacion: 20, cantidad: 1 },
        { denominacion: 0.5, cantidad: 4 },
      ],
      total: 3582,
    },
    metodosPago: [
      { metodo: 'Tarjeta', monto: 5903 },
      { metodo: 'Vales', monto: 100 },
    ],
    totalDeclarado: 9585,
  }

  it('el formulario muestra el conteo que ya se envió, no $0.00', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(
      turnoEn('ESPERANDO_REVISION', {
        movimientos: [{ metodo: 'Tarjeta', totalVentas: 5903 }],
        conteoGuardado,
      }),
    )

    await store.cargarTurnoActivo()

    const billete = (v: number) => store.desgloseEfectivo.billetes.find((b) => b.value === v)
    const moneda = (v: number) => store.desgloseEfectivo.monedas.find((m) => m.value === v)
    expect(billete(500)?.amount).toBe(7)
    expect(billete(20)?.amount).toBe(2)
    expect(billete(1000)?.amount).toBeNull()
    expect(moneda(20)?.amount).toBe(1)
    expect(moneda(0.5)?.amount).toBe(4)
    expect(store.desgloseEfectivo.total).toBe(3582)
    expect(store.totalContadoDeclarado).toBe(9585)
    expect(store.metodosPago.map((m) => [m.metodo, m.monto, m.origen])).toEqual([
      ['Tarjeta', 5903, 'sistema'],
      ['Vales', 100, 'manual'],
    ])
  })

  it('mientras el turno sigue operando no se toca el formulario', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(turnoEn('OPERANDO', { conteoGuardado }))

    await store.cargarTurnoActivo()

    expect(store.totalContadoDeclarado).toBeNull()
    expect(store.desgloseEfectivo.billetes.every((b) => b.amount === null)).toBe(true)
  })
})

describe('M7: efectivo esperado del turno', () => {
  it('usa el efectivo esperado del backend (resta cambio y devoluciones)', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(
      turnoEn('OPERANDO', {
        fondoInicial: 500,
        movimientos: [{ metodo: 'efectivo', totalVentas: 1000 }],
        efectivoEsperado: 1380,
        ventasPorMetodo: [{ metodo: 'efectivo', label: 'Efectivo', total: 880 }],
      }),
    )

    await store.cargarTurnoActivo()

    // Antes: 500 + 1000 = 1500 (sin restar los 120 de cambio).
    expect(store.efectivoDisponible).toBe(1380)
    expect(store.cajaEnNegativo).toBe(false)
    expect(store.ventasPorMetodo).toEqual([{ metodo: 'efectivo', label: 'Efectivo', total: 880 }])
  })

  it('marca la caja en negativo', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(
      turnoEn('OPERANDO', { fondoInicial: 2000, totalRetiros: 12000, efectivoEsperado: -1685 }),
    )

    await store.cargarTurnoActivo()

    expect(store.efectivoDisponible).toBe(-1685)
    expect(store.cajaEnNegativo).toBe(true)
  })

  it('sin el dato del backend conserva el cálculo local', async () => {
    const store = useTurnoCajaStore()
    servicio.cargarTurnoActivo.mockResolvedValue(
      turnoEn('OPERANDO', {
        fondoInicial: 500,
        movimientos: [{ metodo: 'efectivo', totalVentas: 200 }],
      }),
    )

    await store.cargarTurnoActivo()

    expect(store.efectivoDisponible).toBe(700)
  })
})
