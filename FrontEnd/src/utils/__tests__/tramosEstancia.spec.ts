import { describe, expect, it } from 'vitest'

import { seSolapan, tramoParaHoras, validarTramoNuevo } from '@/utils/tramosEstancia'

const t = (min_horas: number, max_horas: number, precio = 100) => ({ min_horas, max_horas, precio })

describe('tramos de estancia: rangos semiabiertos (UX)', () => {
  it('acepta rangos contiguos que comparten un extremo', () => {
    expect(seSolapan(t(0, 1), t(1, 2))).toBe(false)
    expect(validarTramoNuevo(t(1, 2, 130), [t(0, 1, 150)])).toBeNull()
    expect(validarTramoNuevo(t(2, 3), [t(0, 1), t(1, 2)])).toBeNull()
  })

  it('rechaza rangos que se enciman de verdad, con un mensaje que dice con cuál', () => {
    expect(seSolapan(t(0, 2), t(1, 3))).toBe(true)
    expect(validarTramoNuevo(t(1, 3), [t(0, 2)])).toBe('El rango 1–3 h se solapa con el de 0–2 h.')
  })

  it('un tramo de un solo punto choca con otro que lo contiene', () => {
    expect(seSolapan(t(1, 1), t(1, 1))).toBe(true)
    expect(seSolapan(t(1, 1), t(0, 2))).toBe(true)
    expect(seSolapan(t(2, 2), t(1, 2))).toBe(true)
    expect(seSolapan(t(1, 1), t(2, 3))).toBe(false)
  })

  it('valida horas y precio', () => {
    expect(validarTramoNuevo(t(2, 1), [])).toContain('mínimo de horas')
    expect(validarTramoNuevo(t(1, 2, 0), [])).toContain('precio por hora')
  })

  it('en el extremo compartido cobra el tramo que termina ahí, sin importar el orden', () => {
    const tramos = [t(1, 2, 130), t(0, 1, 150)]
    expect(tramoParaHoras(tramos, 1)?.precio).toBe(150)
    expect(tramoParaHoras(tramos, 2)?.precio).toBe(130)
  })

  it('tramos sin extremos compartidos se cotizan igual que antes', () => {
    const tramos = [t(4, 8, 110), t(1, 1, 150), t(2, 3, 130)]
    expect([1, 2, 3, 4, 8].map((h) => tramoParaHoras(tramos, h)?.precio)).toEqual([
      150, 130, 130, 110, 110,
    ])
    // Fuera de todos: el de menor min_horas.
    expect(tramoParaHoras(tramos, 12)?.precio).toBe(150)
    expect(tramoParaHoras([], 2)).toBeNull()
  })
})
