import type { MovimientoPuntos } from '@/types/lealtad'

export interface MovimientoKardex extends MovimientoPuntos {
  /** Cuántos lotes consumió el canje (1 para cualquier otro movimiento). */
  lotes: number
}

/**
 * UX (kardex de lealtad): un canje consume puntos de varios lotes (FIFO por
 * caducidad) y el backend registra un movimiento 'R' por lote, así que un solo
 * canje de 50 pts aparecía como 3 renglones (-9, -8, -33). Aquí se juntan en
 * uno solo para la vista; la contabilidad por lotes no cambia.
 *
 * Los movimientos de un mismo canje se escriben en la misma transacción, así
 * que comparten `creado` (now() de la transacción), celular y comanda.
 */
export function agruparCanjes(movimientos: MovimientoPuntos[]): MovimientoKardex[] {
  const resultado: MovimientoKardex[] = []
  const canjes = new Map<string, MovimientoKardex>()

  for (const m of movimientos) {
    if (m.tipo !== 'R') {
      resultado.push({ ...m, lotes: 1 })
      continue
    }
    const clave = `${m.celular}|${m.creado}|${m.comanda_id ?? ''}`
    const canje = canjes.get(clave)
    if (!canje) {
      const nuevo = { ...m, lotes: 1 }
      canjes.set(clave, nuevo)
      resultado.push(nuevo)
      continue
    }
    canje.puntos += m.puntos
    canje.lotes += 1
    // El saldo después del canje es el del último lote consumido (el menor).
    canje.saldo_resultante = Math.min(canje.saldo_resultante, m.saldo_resultante)
    canje.notas ??= m.notas
  }
  return resultado
}
