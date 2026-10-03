import { beforeEach, describe, expect, it } from 'vitest'

import type { ItemTicket } from '@/components/comandas/TicketItem.vue'
import {
  borrarPedidoEnCurso,
  clavePedidoEnCurso,
  guardarPedidoEnCurso,
  leerPedidoEnCurso,
  unidadesDelPedido,
} from '../pedidoEnCurso'

const pizza = {
  id: 'pizza',
  nombre: 'Pizza',
  precio_unitario: 90,
  tipo: 'A',
  imagen: null,
  sucursal_id: 's1',
  descripcion: null,
  es_combo: false,
} as ItemTicket['producto']

const items: ItemTicket[] = [
  { id: 'r1', producto: pizza, cantidad: 2, notas: '' },
  { id: 'r2', producto: { ...pizza, id: 'combo', es_combo: true }, cantidad: 1, notas: '' },
  {
    id: 'r3',
    producto: { ...pizza, id: 'hotdog' },
    cantidad: 1,
    notas: '',
    es_hijo_combo: true,
    padreTicketId: 'r2',
  },
]

const CLAVE = clavePedidoEnCurso('u1', 's1')

describe('pedido en curso en sessionStorage', () => {
  beforeEach(() => sessionStorage.clear())

  it('guarda y recupera el pedido con su clave de idempotencia', () => {
    guardarPedidoEnCurso(CLAVE, { items, nombreCliente: 'Ana', mesa: '4', idempotencyKey: 'k1' })
    const leido = leerPedidoEnCurso(CLAVE)
    expect(leido?.items).toEqual(items)
    expect(leido?.nombreCliente).toBe('Ana')
    expect(leido?.mesa).toBe('4')
    expect(leido?.idempotencyKey).toBe('k1')
  })

  it('un pedido vacío borra lo guardado', () => {
    guardarPedidoEnCurso(CLAVE, { items, nombreCliente: '', mesa: '', idempotencyKey: null })
    guardarPedidoEnCurso(CLAVE, { items: [], nombreCliente: '', mesa: '', idempotencyKey: null })
    expect(leerPedidoEnCurso(CLAVE)).toBeNull()
  })

  it('ignora datos corruptos y los descarta', () => {
    sessionStorage.setItem(CLAVE, '{"version":1,"items":[{"x":1}]}')
    expect(leerPedidoEnCurso(CLAVE)).toBeNull()
    expect(sessionStorage.getItem(CLAVE)).toBeNull()
    sessionStorage.setItem(CLAVE, 'no es json')
    expect(leerPedidoEnCurso(CLAVE)).toBeNull()
  })

  it('cada usuario y sucursal tiene su propia clave', () => {
    guardarPedidoEnCurso(CLAVE, { items, nombreCliente: '', mesa: '', idempotencyKey: null })
    expect(leerPedidoEnCurso(clavePedidoEnCurso('u2', 's1'))).toBeNull()
    borrarPedidoEnCurso(CLAVE)
    expect(leerPedidoEnCurso(CLAVE)).toBeNull()
  })

  it('cuenta unidades, no renglones, y no cuenta el contenido de los combos', () => {
    expect(unidadesDelPedido(items)).toBe(3)
  })
})
