import { describe, expect, it } from 'vitest'
import { saludoPorHora } from '@/utils/saludo'

describe('saludoPorHora', () => {
  it('de madrugada saluda con buenas noches, no con buenos días', () => {
    expect(saludoPorHora(0)).toBe('Buenas noches')
    expect(saludoPorHora(1)).toBe('Buenas noches')
    expect(saludoPorHora(4)).toBe('Buenas noches')
  })

  it('mañana, tarde y noche', () => {
    expect(saludoPorHora(5)).toBe('Buenos días')
    expect(saludoPorHora(11)).toBe('Buenos días')
    expect(saludoPorHora(12)).toBe('Buenas tardes')
    expect(saludoPorHora(18)).toBe('Buenas tardes')
    expect(saludoPorHora(19)).toBe('Buenas noches')
    expect(saludoPorHora(23)).toBe('Buenas noches')
  })
})
