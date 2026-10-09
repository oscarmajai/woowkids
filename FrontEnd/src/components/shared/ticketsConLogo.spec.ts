import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { describe, expect, it } from 'vitest'

import RetiroParcialCard from '@/components/cierre-caja/RetiroParcialCard.vue'
import TicketPagoEvento from '@/components/eventos/TicketPagoEvento.vue'
import TicketReservacion from '@/components/eventos/TicketReservacion.vue'
import ComprobanteEstancia from '@/components/registro-infantes/ComprobanteEstancia.vue'
import TicketReceipt from '@/components/shared/TicketReceipt.vue'
import type { DetalleOrden } from '@/api/historialApi'

/**
 * Todo ticket que se imprime lleva el logo de Woow Kids. Cada prueba monta un
 * ticket y comprueba que el logo esté; la guarda de abajo revisa el código para
 * que un ticket nuevo no se pueda sumar sin él.
 */
const LOGO = 'img[alt="Woow Kids"]'

const orden = {
  tipo_origen: 'comanda',
  referencia_id: 'o1',
  titulo: 'Mesa 4',
  total_final: 100,
  estado_actual: 'E',
  fecha_hora: '2026-10-08T15:00:00Z',
  motivo_cancelacion: null,
  creado_por_nombre: 'Ana',
  metodos_pago: [],
  detalles: [],
  comanda_id: 'c1',
  ticket_numero: 'T1',
  nombre_cliente: null,
} as unknown as DetalleOrden

describe('todo ticket lleva el logo', () => {
  it('ticket de venta (comanda, estancia y evento)', () => {
    for (const tipo of ['comanda', 'estancia', 'reservacion'] as const) {
      const w = mount(TicketReceipt, {
        props: { orden: { ...orden, tipo_origen: tipo }, anchoMm: 80 },
      })
      expect(w.find(LOGO).exists(), `venta ${tipo}`).toBe(true)
    }
  })

  it('comprobante de entrada de estancia (y su reimpresión con QR)', () => {
    for (const reimpresion of [false, true]) {
      const w = mount(ComprobanteEstancia, {
        props: {
          datos: {
            sucursal: 'Plaza',
            cajero: 'Ana',
            fecha: new Date(),
            tutor: 'Laura',
            ninos: [{ nombre: 'Leo', edad: 5 }],
            salidaEstimada: '14:00',
            total: 100,
            qrCodeUrl: 'data:image/png;base64,qr',
            reimpresion,
          },
        },
      })
      expect(w.find(LOGO).exists(), `reimpresion=${reimpresion}`).toBe(true)
    }
  })

  it('comprobante de reservación', () => {
    const w = mount(TicketReservacion, {
      props: {
        folio: 'c82b16d2-0f90',
        sucursal: 'Plaza',
        clienteNombre: 'Diego',
        clienteTelefono: '3500000000',
        clienteEmail: null,
        tipoEvento: 'Cumpleaños',
        fechaEvento: '8 oct',
        horario: '09:00',
        numeroNinos: 5,
        paqueteNombre: 'Clásico',
        conceptos: [],
        total: 1000,
        anticipo: 500,
        metodosPago: 'Efectivo',
      },
    })
    expect(w.find(LOGO).exists()).toBe(true)
  })

  it('comprobante de pago de evento', () => {
    const w = mount(TicketPagoEvento, {
      props: {
        folio: 'c82b16d2-0f90',
        sucursal: 'Plaza',
        clienteNombre: 'Diego',
        tipoEvento: 'Cumpleaños',
        fechaEvento: '8 oct',
        totalEvento: 1000,
        montoPagado: 500,
        totalPagadoAcumulado: 500,
        saldoPendiente: 500,
        metodosPago: 'Efectivo',
      },
    })
    expect(w.find(LOGO).exists()).toBe(true)
  })

  it('comprobante de retiro parcial', async () => {
    const w = mount(RetiroParcialCard)
    ;(w.vm as unknown as { comprobante: unknown }).comprobante = {
      id: 'r1',
      turnoId: 't1',
      concepto: 'Pago a proveedor',
      tipoDestinatario: 'Proveedor',
      monto: 100,
      observaciones: null,
      creado: '2026-10-08T15:00:00Z',
    }
    await nextTick()
    expect(w.find(LOGO).exists()).toBe(true)
  })
})

describe('guarda: ningún punto de impresión sin logo', () => {
  // Todo .vue del proyecto, como texto.
  const fuentes = import.meta.glob('/src/**/*.vue', {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>

  /**
   * Archivos que imprimen pero no dibujan el ticket ellos mismos: el logo viene
   * del componente hijo que se indica (ya cubierto arriba), o no es un ticket.
   */
  const IMPRIME_UN_HIJO: Record<string, string> = {
    '/src/components/historial/DetalleOrdenPagada.vue': 'TicketReceipt',
    '/src/components/registro-infantes/PrintVoucher.vue': 'ComprobanteEstancia',
    '/src/components/control-acceso/ReimprimirComprobanteDialog.vue': 'ComprobanteEstancia',
    // Documento legal (aviso de privacidad), no un ticket: lleva su propia cabecera.
    '/src/pages/AvisoPrivacidadPage.vue': 'NO_ES_TICKET',
  }

  const imprimen = Object.entries(fuentes).filter(
    ([ruta, texto]) =>
      !ruta.endsWith('.spec.ts') &&
      (texto.includes('printTicketElement(') || texto.includes('window.print()')),
  )

  it('encuentra los puntos de impresión del proyecto', () => {
    expect(imprimen.length).toBeGreaterThanOrEqual(8)
  })

  it.each(imprimen.map(([ruta]) => [ruta]))(
    '%s lleva logo o imprime un componente que lo lleva',
    (ruta) => {
      const texto = fuentes[ruta]!
      const hijo = IMPRIME_UN_HIJO[ruta]
      if (hijo === 'NO_ES_TICKET') return
      if (hijo) {
        expect(texto, `${ruta} debe usar <${hijo}>`).toContain(`<${hijo}`)
        const rutaHijo = Object.keys(fuentes).find((r) => r.endsWith(`/${hijo}.vue`))!
        expect(fuentes[rutaHijo], `${hijo} debe llevar <TicketLogo`).toContain('<TicketLogo')
      } else {
        expect(texto, `${ruta} imprime y no tiene <TicketLogo`).toContain('<TicketLogo')
      }
    },
  )
})
