import { describe, expect, it } from 'vitest'

import { textoDevolucion, textoDevolucionesMetodo, totalDevoluciones } from '../devoluciones'
import type { DevolucionArqueo, FilaBalance } from '@/types/turnoCaja'

function fila(metodo: string, devoluciones: number): FilaBalance {
  return { metodo, label: metodo, declarado: 0, esperado: 0, diferencia: 0, devoluciones }
}

function devolucion(extra: Partial<DevolucionArqueo> = {}): DevolucionArqueo {
  return {
    id: 'd1',
    comandaId: 'c1',
    ticketNumero: 'T-12',
    metodoPagoNombre: 'Tarjeta',
    esEfectivo: false,
    monto: 70,
    origen: 'cancelacion',
    motivo: 'Cliente se arrepintió',
    autorizadoPorNombre: 'Admin Puebla',
    creadoPorNombre: 'Cajera',
    creado: '2026-10-03T12:00:00',
    ...extra,
  }
}

describe('devoluciones en el arqueo (A4)', () => {
  it('suma lo devuelto en todos los métodos', () => {
    expect(totalDevoluciones([fila('efectivo', 40), fila('tarjeta', 30), fila('otro', 0)])).toBe(70)
    expect(totalDevoluciones([])).toBe(0)
  })

  it('muestra las devoluciones del método solo si las hubo', () => {
    expect(textoDevolucionesMetodo(fila('tarjeta', 70))).toBe('Devoluciones −$70.00')
    expect(textoDevolucionesMetodo(fila('tarjeta', 0))).toBe('')
  })

  it('describe cada devolución con su tipo, motivo y quién autorizó', () => {
    expect(textoDevolucion(devolucion())).toBe(
      'T-12 · $70.00 Tarjeta · Cancelación: Cliente se arrepintió · autorizó Admin Puebla',
    )
    expect(
      textoDevolucion(
        devolucion({
          origen: 'entregada',
          metodoPagoNombre: null,
          esEfectivo: true,
          motivo: null,
          autorizadoPorNombre: null,
        }),
      ),
    ).toBe('T-12 · $70.00 Efectivo · Devolución de orden entregada')
  })
})
