import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TicketReceipt from '../TicketReceipt.vue'
import type { DetalleOrden, DetalleProducto } from '@/api/historialApi'

function detalle(id: string, nombre: string, extra: Partial<DetalleProducto> = {}) {
  return {
    id,
    producto_nombre: nombre,
    cantidad: 1,
    precio_unitario: 0,
    importe: 0,
    notas_especiales: null,
    nombre_combo_padre: null,
    ...extra,
  }
}

function orden(extra: Partial<DetalleOrden> = {}): DetalleOrden {
  return {
    tipo_origen: 'comanda',
    referencia_id: 'c1',
    titulo: 'A15',
    total_final: 170,
    estado_actual: 'P',
    fecha_hora: '2026-10-03T12:00:00-06:00',
    motivo_cancelacion: null,
    creado_por_nombre: 'Diego López',
    metodos_pago: [{ metodo_pago_nombre: 'Efectivo', monto: 200, notas_pago: null }],
    detalles: [detalle('p1', 'Pizza', { precio_unitario: 170, importe: 170 })],
    comanda_id: 'c1',
    ticket_numero: 'A15',
    nombre_cliente: 'Mariana',
    cambio: 30,
    sucursal: {
      nombre: 'Woow Kids Plaza Patria',
      direccion: 'Av. Patria 1950',
      ciudad: 'Zapopan',
      estado: 'Jalisco',
      codigo_postal: '45160',
      telefono: '3333333333',
    },
    ...extra,
  }
}

describe('TicketReceipt', () => {
  it('M12: encabezado con la sucursal de la venta, cliente y cambio', () => {
    const texto = mount(TicketReceipt, { props: { orden: orden(), anchoMm: 80 } }).text()
    expect(texto).toContain('Woow Kids Plaza Patria')
    expect(texto).toContain('Av. Patria 1950')
    expect(texto).toContain('45160 Zapopan, Jalisco.')
    expect(texto).toContain('Tel. 3333333333')
    expect(texto).not.toContain('Nigromante')
    expect(texto).toContain('CLIENTE: Mariana')
    expect(texto).toMatch(/CAMBIO\s*\$30\.00/)
  })

  it('sin cambio no imprime la línea de cambio', () => {
    const texto = mount(TicketReceipt, {
      props: { orden: orden({ cambio: 0 }), anchoMm: 80 },
    }).text()
    expect(texto).not.toContain('CAMBIO')
  })

  it('M13: un combo dividido lista solo sus productos, sin repetir los del otro', () => {
    const combo = { nombre_combo_padre: 'Combo Hot dog' }
    const detalles = [
      detalle('c1', 'Combo Hot dog', { precio_unitario: 120, importe: 120 }),
      detalle('c2', 'Combo Hot dog', { precio_unitario: 120, importe: 120 }),
      detalle('h1', 'Hot dog', { ...combo, detalle_padre_id: 'c1' }),
      detalle('h2', 'Refresco', { ...combo, detalle_padre_id: 'c1' }),
      detalle('h3', 'Hot dog', { ...combo, detalle_padre_id: 'c2' }),
      detalle('h4', 'Refresco', {
        ...combo,
        detalle_padre_id: 'c2',
        notas_especiales: 'Sin hielo',
      }),
    ]
    const wrapper = mount(TicketReceipt, {
      props: { orden: orden({ detalles, total_final: 240 }), anchoMm: 80 },
    })
    const filas = wrapper.findAll('.ticket-row').map((f) => f.text())
    expect(filas).toHaveLength(6)
    expect(filas.filter((f) => f.includes('Sin hielo'))).toHaveLength(1)
  })

  it('M13: 2x combo en un renglón suma sus productos', () => {
    const combo = { nombre_combo_padre: 'Combo Hot dog', detalle_padre_id: 'c1' }
    const detalles = [
      detalle('c1', 'Combo Hot dog', { cantidad: 2, precio_unitario: 120, importe: 240 }),
      detalle('h1', 'Hot dog', combo),
      detalle('h2', 'Refresco', combo),
      detalle('h3', 'Hot dog', combo),
      detalle('h4', 'Refresco', combo),
    ]
    const wrapper = mount(TicketReceipt, {
      props: { orden: orden({ detalles, total_final: 240 }), anchoMm: 80 },
    })
    const filas = wrapper.findAll('.ticket-row').map((f) => f.text())
    expect(filas).toHaveLength(3)
    expect(filas[1]).toContain('2x Hot dog')
    expect(filas[2]).toContain('2x Refresco')
  })
})
