import type { DevolucionArqueo, FilaBalance, OrigenDevolucion } from '@/types/turnoCaja'
import { formatMXN } from '@/utils/formatoMoneda'

/**
 * Textos de las devoluciones a clientes en el arqueo. Cada devolución ya
 * viene restada del esperado de su método; aquí solo se muestra.
 */

const ETIQUETA_ORIGEN: Record<OrigenDevolucion, string> = {
  cancelacion: 'Cancelación',
  entregada: 'Devolución de orden entregada',
}

/** Suma de lo devuelto en todos los métodos del arqueo. */
export function totalDevoluciones(filas: FilaBalance[]): number {
  return filas.reduce((suma, fila) => suma + (fila.devoluciones || 0), 0)
}

/** "Devoluciones −$70.00" si el método tuvo devoluciones; vacío si no. */
export function textoDevolucionesMetodo(fila: FilaBalance): string {
  return fila.devoluciones > 0 ? `Devoluciones −${formatMXN(fila.devoluciones)}` : ''
}

/** Renglón de una devolución: orden, tipo y motivo, método y quién autorizó. */
export function textoDevolucion(devolucion: DevolucionArqueo): string {
  const metodo = devolucion.metodoPagoNombre ?? (devolucion.esEfectivo ? 'Efectivo' : '—')
  const tipo = ETIQUETA_ORIGEN[devolucion.origen]
  const partes = [
    `${devolucion.ticketNumero ?? '—'} · ${formatMXN(devolucion.monto)} ${metodo}`,
    devolucion.motivo ? `${tipo}: ${devolucion.motivo}` : tipo,
  ]
  if (devolucion.autorizadoPorNombre) partes.push(`autorizó ${devolucion.autorizadoPorNombre}`)
  return partes.join(' · ')
}
