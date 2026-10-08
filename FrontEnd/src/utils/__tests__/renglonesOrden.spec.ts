import { describe, expect, it } from 'vitest'

import type { DetalleProducto } from '@/api/historialApi'
import { agruparPorRenglon, resumirHijos } from '../renglonesOrden'

const COMBO = 'Combo Hot dog'

function renglon(id: string, extra: Partial<DetalleProducto> = {}): DetalleProducto {
  return {
    id,
    producto_nombre: COMBO,
    cantidad: 1,
    precio_unitario: 120,
    importe: 120,
    notas_especiales: null,
    nombre_combo_padre: null,
    ...extra,
  }
}

function hijo(id: string, nombre: string, extra: Partial<DetalleProducto> = {}): DetalleProducto {
  return {
    id,
    producto_nombre: nombre,
    cantidad: 1,
    precio_unitario: 0,
    importe: 0,
    notas_especiales: null,
    nombre_combo_padre: COMBO,
    ...extra,
  }
}

describe('agruparPorRenglon', () => {
  it('combo dividido: cada renglón lleva solo sus productos', () => {
    const detalles = [
      renglon('c1'),
      renglon('c2'),
      hijo('h1', 'Hot dog', { detalle_padre_id: 'c1', id_combo_padre: 'i1' }),
      hijo('h2', 'Refresco', { detalle_padre_id: 'c1', id_combo_padre: 'i1' }),
      hijo('h3', 'Hot dog', { detalle_padre_id: 'c2', id_combo_padre: 'i2' }),
      hijo('h4', 'Refresco', {
        detalle_padre_id: 'c2',
        id_combo_padre: 'i2',
        notas_especiales: 'Sin hielo',
      }),
    ]
    const grupos = agruparPorRenglon(detalles)
    expect(grupos.map((g) => [g.renglon.id, g.hijos.map((h) => h.id)])).toEqual([
      ['c1', ['h1', 'h2']],
      ['c2', ['h3', 'h4']],
    ])
  })

  it('órdenes viejas sin renglón: reparte las unidades entre los combos en orden', () => {
    const detalles = [
      renglon('c1'),
      renglon('c2'),
      hijo('h1', 'Hot dog', { id_combo_padre: 'i1' }),
      hijo('h2', 'Refresco', { id_combo_padre: 'i1' }),
      hijo('h3', 'Hot dog', { id_combo_padre: 'i2' }),
      hijo('h4', 'Refresco', { id_combo_padre: 'i2' }),
    ]
    const grupos = agruparPorRenglon(detalles)
    expect(grupos.map((g) => g.hijos.map((h) => h.id))).toEqual([
      ['h1', 'h2'],
      ['h3', 'h4'],
    ])
  })

  it('un hijo sin combo en la orden se muestra como renglón propio', () => {
    const grupos = agruparPorRenglon([hijo('h1', 'Hot dog')])
    expect(grupos).toHaveLength(1)
    expect(grupos[0]?.renglon.id).toBe('h1')
  })

  it('los productos sueltos quedan sin hijos', () => {
    const suelto = renglon('p1', { producto_nombre: 'Pizza' })
    expect(agruparPorRenglon([suelto])).toEqual([{ renglon: suelto, hijos: [] }])
  })
})

describe('resumirHijos', () => {
  it('suma los productos iguales con la misma nota (2x combo → 2x Hot dog)', () => {
    const resumen = resumirHijos([
      hijo('h1', 'Hot dog'),
      hijo('h2', 'Refresco'),
      hijo('h3', 'Hot dog'),
      hijo('h4', 'Refresco', { notas_especiales: 'Sin hielo' }),
    ])
    expect(resumen.map((h) => [h.producto_nombre, h.cantidad, h.notas_especiales])).toEqual([
      ['Hot dog', 2, null],
      ['Refresco', 1, null],
      ['Refresco', 1, 'Sin hielo'],
    ])
  })
})
