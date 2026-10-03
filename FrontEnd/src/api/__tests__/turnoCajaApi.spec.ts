import { describe, it, expect, beforeEach, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
vi.mock('@/api/axiosClient', () => ({ apiClient: { get, post } }))

const { turnoCajaApi } = await import('@/api/turnoCajaApi')

const TURNO_RAW = {
  id: 't1',
  sucursal_id: 's1',
  sucursal_nombre: 'Plaza Patria',
  cajero_id: 'c1',
  cajero_nombre: 'Diego',
  terminal: 'CAJA 01',
  caja_nombre: 'Caja Patria 1',
  estado: 'ESPERANDO_REVISION',
  fondo_inicial: '500.00',
  fecha_apertura: '2026-10-03T08:00:00',
  observaciones_apertura: 'Fondo con monedas',
  total_ventas: '1300.00',
  total_retiros: '200.00',
  total_ingresos: '50.00',
  numero_ventas: 3,
  total_vendido: '1180.00',
  total_cambio: '120.00',
  efectivo_esperado: '-15.50',
  ventas_por_metodo: [{ metodo: 'efectivo', label: 'Efectivo', total: '880.00' }],
  movimientos: [],
  conteo_guardado: {
    desglose_efectivo: {
      billetes: [{ denominacion: '500', cantidad: 7 }],
      monedas: [{ denominacion: '0.5', cantidad: 2 }],
      total: '3501',
    },
    metodos_pago: [{ metodo: 'Tarjeta', monto: '5903' }],
    total_declarado: '9404',
  },
}

describe('turnoCajaApi.obtenerActivo (B4 / M6 / M7 / B23)', () => {
  beforeEach(() => {
    get.mockReset()
  })

  it('pide el turno con opcional=true y un null es "sin turno"', async () => {
    get.mockResolvedValue({ data: null })

    expect(await turnoCajaApi.obtenerActivo()).toBeNull()
    expect(get).toHaveBeenCalledWith('/turnos-caja/activo', { params: { opcional: true } })

    await turnoCajaApi.obtenerActivo('s2')
    expect(get).toHaveBeenLastCalledWith('/turnos-caja/activo', {
      params: { sucursal_id: 's2', opcional: true },
    })
  })

  it('mapea los campos nuevos del turno', async () => {
    get.mockResolvedValue({ data: TURNO_RAW })

    const turno = await turnoCajaApi.obtenerActivo()

    expect(turno).toMatchObject({
      cajaNombre: 'Caja Patria 1',
      observacionesApertura: 'Fondo con monedas',
      totalVendido: 1180,
      totalCambio: 120,
      efectivoEsperado: -15.5,
      ventasPorMetodo: [{ metodo: 'efectivo', label: 'Efectivo', total: 880 }],
      conteoGuardado: {
        desgloseEfectivo: {
          billetes: [{ denominacion: 500, cantidad: 7 }],
          monedas: [{ denominacion: 0.5, cantidad: 2 }],
          total: 3501,
        },
        metodosPago: [{ metodo: 'Tarjeta', monto: 5903 }],
        totalDeclarado: 9404,
      },
    })
  })

  it('sin efectivo_esperado (backend viejo) lo deja en null', async () => {
    const viejo: Record<string, unknown> = { ...TURNO_RAW }
    delete viejo.efectivo_esperado
    get.mockResolvedValue({ data: viejo })

    const turno = await turnoCajaApi.obtenerActivo()

    expect(turno?.efectivoEsperado).toBeNull()
  })
})

describe('turnoCajaApi.obtenerTurnos (M8)', () => {
  it('expone si cada horario está vigente', async () => {
    get.mockResolvedValue({
      data: [
        { id: 'h1', nombre: 'Matutino', hora_inicio: '08:00:00', hora_fin: '15:00:00' },
        {
          id: 'h2',
          nombre: 'Vespertino',
          hora_inicio: '15:00:00',
          hora_fin: '23:59:00',
          vigente: true,
        },
      ],
    })

    const turnos = await turnoCajaApi.obtenerTurnos()

    expect(turnos.map((t) => [t.id, t.vigente])).toEqual([
      ['h1', false],
      ['h2', true],
    ])
  })
})

describe('turnoCajaApi.registrarIngreso (motivo)', () => {
  it('manda el motivo del ingreso', async () => {
    post.mockResolvedValue({
      data: {
        id: 1,
        apertura_caja_id: 't1',
        monto: '200.00',
        observaciones: 'Cambio',
        creado: 'x',
      },
    })

    const resp = await turnoCajaApi.registrarIngreso({
      turnoId: 't1',
      monto: 200,
      observaciones: 'Cambio',
    })

    expect(post).toHaveBeenCalledWith('/turnos-caja/ingreso-efectivo', {
      apertura_caja_id: 't1',
      monto: 200,
      observaciones: 'Cambio',
    })
    expect(resp.observaciones).toBe('Cambio')
  })
})
