import { describe, expect, it } from 'vitest'

import {
  compraPorRecibir,
  formatCostoUnitario,
  sumarBadgesGrupo,
  tituloAlertasStock,
} from '../inventario'

// Intl usa espacios especiales en algunos entornos: se comparan sin ellos.
const limpio = (s: string) => s.replace(/\s/g, '')

describe('formatCostoUnitario (M21)', () => {
  it('no redondea a centavos el costo por gramo o mililitro', () => {
    expect(limpio(formatCostoUnitario('0.042692'))).toBe('$0.042692')
    expect(limpio(formatCostoUnitario(0.12231))).toBe('$0.12231')
  })

  it('muestra al menos dos decimales', () => {
    expect(limpio(formatCostoUnitario('12.500000'))).toBe('$12.50')
    expect(limpio(formatCostoUnitario(null))).toBe('$0.00')
  })
})

describe('compraPorRecibir (B6)', () => {
  it('cuenta las pendientes y las parciales', () => {
    expect(compraPorRecibir('P')).toBe(true)
    expect(compraPorRecibir('PARCIAL')).toBe(true)
    expect(compraPorRecibir('R')).toBe(false)
    expect(compraPorRecibir('C')).toBe(false)
  })
})

describe('tituloAlertasStock (B7)', () => {
  it('separa bajo mínimo de por reordenar', () => {
    expect(tituloAlertasStock(1, 1)).toBe('1 insumo bajo mínimo · 1 por reordenar')
    expect(tituloAlertasStock(2, 0)).toBe('2 insumos bajo mínimo')
    expect(tituloAlertasStock(0, 1)).toBe('1 insumo por reordenar')
  })
})

describe('sumarBadgesGrupo (B7)', () => {
  it('cuenta una sola vez dos ítems con el mismo contador', () => {
    const alertas = { count: 2, tone: 'warn' as const, fuente: 'alertas-inventario' }
    expect(sumarBadgesGrupo([alertas, null, alertas])).toBe(2)
  })

  it('suma contadores de fuentes distintas o sin fuente', () => {
    expect(
      sumarBadgesGrupo([
        { count: 2, tone: 'warn', fuente: 'a' },
        { count: 3, tone: 'warn', fuente: 'b' },
        { count: 1, tone: 'warn' },
      ]),
    ).toBe(6)
  })
})
