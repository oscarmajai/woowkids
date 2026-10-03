/**
 * inventario.ts
 *
 * Reglas de presentación de inventario y compras que comparten varias
 * pantallas (Insumos, Compras, Reporte de Stock, Inicio y el menú).
 */
import type { EstadoCompra } from '@/types/compra'
import type { NavBadge } from '@/types/navigation'

const formateadorCostoUnitario = new Intl.NumberFormat('es-MX', {
  style: 'currency',
  currency: 'MXN',
  minimumFractionDigits: 2,
  maximumFractionDigits: 6,
})

/**
 * Costo por unidad base de un insumo (M21). En insumos por gramo o mililitro
 * el costo es de centavos o fracciones ($0.042692/ml): con 2 decimales se
 * leía $0.04. Los montos totales siguen con `formatMXN` (2 decimales).
 * @example formatCostoUnitario(0.042692) → "$0.042692"
 * @example formatCostoUnitario(12.5) → "$12.50"
 */
export function formatCostoUnitario(valor: number | string | null | undefined): string {
  return formateadorCostoUnitario.format(Number(valor ?? 0))
}

/** Una compra sigue pendiente de recibir mientras no llegue completa (B6). */
export function compraPorRecibir(estado: EstadoCompra): boolean {
  return estado === 'P' || estado === 'PARCIAL'
}

/**
 * Título del aviso de stock de Inicio (B7): separa "bajo mínimo" de "por
 * reordenar" (antes todo salía como "N insumos bajo mínimo").
 * @example tituloAlertasStock(1, 1) → "1 insumo bajo mínimo · 1 por reordenar"
 */
export function tituloAlertasStock(criticos: number, porReordenar: number): string {
  const partes: string[] = []
  if (criticos > 0) partes.push(`${criticos} ${criticos === 1 ? 'insumo' : 'insumos'} bajo mínimo`)
  if (porReordenar > 0) {
    partes.push(
      criticos > 0
        ? `${porReordenar} por reordenar`
        : `${porReordenar} ${porReordenar === 1 ? 'insumo' : 'insumos'} por reordenar`,
    )
  }
  return partes.join(' · ')
}

/**
 * Contador de un grupo del menú cuando está cerrado (B7). Varios ítems pueden
 * mostrar el mismo contador (Insumos y Reporte de Stock muestran las mismas
 * alertas): cada `fuente` cuenta una sola vez para no sumarlo doble.
 */
export function sumarBadgesGrupo(badges: Array<NavBadge | null | undefined>): number {
  const vistas = new Set<string>()
  let total = 0
  for (const badge of badges) {
    if (!badge) continue
    if (badge.fuente) {
      if (vistas.has(badge.fuente)) continue
      vistas.add(badge.fuente)
    }
    total += badge.count
  }
  return total
}
