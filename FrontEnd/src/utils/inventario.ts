/**
 * inventario.ts
 *
 * Reglas de presentación de inventario y compras que comparten varias
 * pantallas (Insumos, Compras, Reporte de Stock, Inicio y el menú).
 */
import type { EstadoCompra } from '@/types/compra'

/** Una compra sigue pendiente de recibir mientras no llegue completa (B6). */
export function compraPorRecibir(estado: EstadoCompra): boolean {
  return estado === 'P' || estado === 'PARCIAL'
}
