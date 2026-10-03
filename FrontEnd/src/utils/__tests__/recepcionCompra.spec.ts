import { describe, expect, it } from 'vitest'

import {
  armarRecepcion,
  cantidadCapturada,
  lineaExcedida,
  type LineaRecepcionUI,
} from '../recepcionCompra'

const linea = (detalle_id: string, pendiente: number, ahora: LineaRecepcionUI['ahora']) => ({
  detalle_id,
  insumo_nombre: `Insumo ${detalle_id}`,
  unidad: 'kg',
  pedido: pendiente,
  recibido: 0,
  pendiente,
  ahora,
})

describe('armarRecepcion (A12)', () => {
  it('manda todas las líneas, incluidas las que quedan en 0', () => {
    const payload = armarRecepcion([
      linea('caja', 2, 1),
      linea('kg', 1.5, 0),
      linea('garrafa', 2, 2),
      linea('l', 3, 0),
    ])
    expect(payload).toEqual({
      lineas: [
        { detalle_id: 'caja', cantidad: '1' },
        { detalle_id: 'kg', cantidad: '0' },
        { detalle_id: 'garrafa', cantidad: '2' },
        { detalle_id: 'l', cantidad: '0' },
      ],
    })
  })

  it('un campo vacío o inválido se manda como 0, nunca se omite', () => {
    const payload = armarRecepcion([linea('a', 5, ''), linea('b', 5, null), linea('c', 5, -2)])
    expect(payload.lineas).toEqual([
      { detalle_id: 'a', cantidad: '0' },
      { detalle_id: 'b', cantidad: '0' },
      { detalle_id: 'c', cantidad: '0' },
    ])
  })

  it('conserva decimales', () => {
    expect(armarRecepcion([linea('a', 2, 1.25)]).lineas).toEqual([
      { detalle_id: 'a', cantidad: '1.25' },
    ])
  })
})

describe('validación de la captura', () => {
  it('detecta una línea que excede lo pendiente', () => {
    expect(lineaExcedida(linea('a', 2, 3))).toBe(true)
    expect(lineaExcedida(linea('a', 2, 2))).toBe(false)
  })

  it('cantidadCapturada normaliza vacíos a 0', () => {
    expect(cantidadCapturada({ ahora: '' })).toBe(0)
    expect(cantidadCapturada({ ahora: '1.5' })).toBe(1.5)
  })
})
