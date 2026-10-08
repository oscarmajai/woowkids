import { describe, expect, it } from 'vitest'

import {
  compraPorRecibir,
  diferenciaConteo,
  formatCostoUnitario,
  pasoCantidadReceta,
  sumarBadgesGrupo,
  tituloAlertasStock,
  totalConIva,
} from '../inventario'

// Intl usa espacios especiales en algunos entornos: se comparan sin ellos.
const limpio = (s: string) => s.replace(/\s/g, '')

describe('formatCostoUnitario', () => {
  it('no redondea a centavos el costo por gramo o mililitro', () => {
    expect(limpio(formatCostoUnitario('0.042692'))).toBe('$0.042692')
    expect(limpio(formatCostoUnitario(0.12231))).toBe('$0.12231')
  })

  it('muestra al menos dos decimales', () => {
    expect(limpio(formatCostoUnitario('12.500000'))).toBe('$12.50')
    expect(limpio(formatCostoUnitario(null))).toBe('$0.00')
  })
})

describe('diferenciaConteo (conteo físico)', () => {
  it('reporta la merma en positivo, sin doble negativo', () => {
    expect(diferenciaConteo(6400, 6500)).toEqual({ tipo: 'merma', cantidad: 100 })
  })

  it('distingue sobrante y coincidencia, redondeando a 3 decimales', () => {
    expect(diferenciaConteo(10.5, 10)).toEqual({ tipo: 'entrada', cantidad: 0.5 })
    expect(diferenciaConteo(0.3, 0.1 + 0.2)).toEqual({ tipo: 'igual', cantidad: 0 })
  })
})

describe('compraPorRecibir', () => {
  it('cuenta las pendientes y las parciales', () => {
    expect(compraPorRecibir('P')).toBe(true)
    expect(compraPorRecibir('PARCIAL')).toBe(true)
    expect(compraPorRecibir('R')).toBe(false)
    expect(compraPorRecibir('C')).toBe(false)
  })
})

describe('totalConIva (UX compras)', () => {
  it('suma el IVA capturado al total de las líneas', () => {
    expect(totalConIva('1950.00', '300.00')).toBe(2250)
    expect(totalConIva(100, null)).toBe(100)
    expect(totalConIva(100, '')).toBe(100)
  })
})

describe('tituloAlertasStock', () => {
  it('separa bajo mínimo de por reordenar', () => {
    expect(tituloAlertasStock(1, 1)).toBe('1 insumo bajo mínimo · 1 por reordenar')
    expect(tituloAlertasStock(2, 0)).toBe('2 insumos bajo mínimo')
    expect(tituloAlertasStock(0, 1)).toBe('1 insumo por reordenar')
  })
})

describe('sumarBadgesGrupo', () => {
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

describe('pasoCantidadReceta', () => {
  it('sube de 1 en 1 los insumos por pieza', () => {
    expect(pasoCantidadReceta({ tipo: 'pieza', factor_a_base: '1.000000' })).toBe(1)
  })

  it('sube de 0.5 en 0.5 los insumos en kg o l', () => {
    expect(pasoCantidadReceta({ tipo: 'masa', factor_a_base: '1000.000000' })).toBe(0.5)
    expect(pasoCantidadReceta({ tipo: 'volumen', factor_a_base: '1000.000000' })).toBe(0.5)
  })

  it('deja el paso fino en g, ml o sin insumo elegido', () => {
    expect(pasoCantidadReceta({ tipo: 'masa', factor_a_base: '1.000000' })).toBe(0.001)
    expect(pasoCantidadReceta({ tipo: 'volumen', factor_a_base: '1.000000' })).toBe(0.001)
    expect(pasoCantidadReceta(null)).toBe(0.001)
  })
})
