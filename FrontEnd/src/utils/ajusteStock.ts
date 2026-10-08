/**
 * Validación del diálogo "Registrar ajuste" de Insumos.
 *
 * `v-model.number` deja un número, o `''` cuando el input se vacía o trae algo
 * que no se puede convertir. El backend exige cantidad > 0 en el ajuste manual
 * y stock contado >= 0 en el conteo físico: el botón se deshabilita antes de
 * mandar algo que el servidor va a rechazar.
 */

type ValorNumerico = number | string | null | undefined

function aNumero(valor: ValorNumerico): number | null {
  if (valor === null || valor === undefined || valor === '') return null
  const n = typeof valor === 'number' ? valor : Number(valor)
  return Number.isFinite(n) ? n : null
}

/** Cantidad del ajuste manual: número mayor que 0. */
export function esCantidadAjusteValida(valor: ValorNumerico): boolean {
  const n = aNumero(valor)
  return n !== null && n > 0
}

/** Stock real contado del conteo físico: número mayor o igual que 0. */
export function esStockContadoValido(valor: ValorNumerico): boolean {
  const n = aNumero(valor)
  return n !== null && n >= 0
}

export const MENSAJE_CANTIDAD_AJUSTE = 'La cantidad debe ser mayor que 0.'
export const MENSAJE_STOCK_CONTADO = 'El stock contado no puede ser negativo.'

/** Reglas de Quasar (`:rules`) para los dos inputs del diálogo. */
export const reglaCantidadAjuste = (valor: ValorNumerico): true | string =>
  esCantidadAjusteValida(valor) || MENSAJE_CANTIDAD_AJUSTE

export const reglaStockContado = (valor: ValorNumerico): true | string =>
  esStockContadoValido(valor) || MENSAJE_STOCK_CONTADO
