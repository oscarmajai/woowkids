import { describe, it, expect } from 'vitest'
import {
  esCantidadAjusteValida,
  esStockContadoValido,
  reglaCantidadAjuste,
  reglaStockContado,
  MENSAJE_CANTIDAD_AJUSTE,
  MENSAJE_STOCK_CONTADO,
} from '@/utils/ajusteStock'

describe('ajusteStock (B8 / inventario B14)', () => {
  it('la cantidad negativa del ajuste manual no es válida', () => {
    expect(esCantidadAjusteValida(-5)).toBe(false)
    expect(reglaCantidadAjuste(-5)).toBe(MENSAJE_CANTIDAD_AJUSTE)
  })

  it('cero, vacío y no numérico tampoco', () => {
    expect(esCantidadAjusteValida(0)).toBe(false)
    expect(esCantidadAjusteValida('')).toBe(false)
    expect(esCantidadAjusteValida(null)).toBe(false)
    expect(esCantidadAjusteValida('abc')).toBe(false)
    expect(esCantidadAjusteValida(Number.NaN)).toBe(false)
  })

  it('una cantidad positiva sí', () => {
    expect(esCantidadAjusteValida(0.5)).toBe(true)
    expect(esCantidadAjusteValida('3')).toBe(true)
    expect(reglaCantidadAjuste(5)).toBe(true)
  })

  it('el stock contado admite 0 pero no negativos', () => {
    expect(esStockContadoValido(0)).toBe(true)
    expect(esStockContadoValido(12.5)).toBe(true)
    expect(esStockContadoValido(-1)).toBe(false)
    expect(esStockContadoValido('')).toBe(false)
    expect(reglaStockContado(-1)).toBe(MENSAJE_STOCK_CONTADO)
  })
})
