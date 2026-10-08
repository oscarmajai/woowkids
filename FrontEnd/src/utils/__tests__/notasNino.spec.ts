import { describe, expect, it } from 'vitest'

import { avisosDeNotas, notaVisible } from '@/utils/notasNino'

describe('notas / alergias del niño', () => {
  it('una nota en blanco no cuenta', () => {
    expect(notaVisible(null)).toBeNull()
    expect(notaVisible('   ')).toBeNull()
    expect(notaVisible(' Alérgico al cacahuate ')).toBe('Alérgico al cacahuate')
  })

  it('genera un aviso por cada niño con notas', () => {
    const avisos = avisosDeNotas([
      { detalleId: 'd1', nino: 'Santiago', pulsera: 'WK-0000001', notas: 'Alérgico al cacahuate' },
      { detalleId: 'd2', nino: 'Regina', pulsera: 'WK-0000002', notas: null },
      { detalleId: 'd3', nino: 'Emilio', pulsera: 'WK-0000005', notas: 'Intolerante a la lactosa' },
    ])

    expect(avisos.map((a) => a.key)).toEqual(['notas-d1', 'notas-d3'])
    expect(avisos[0].title).toBe('Santiago: notas / alergias')
    expect(avisos[0].detail).toContain('Alérgico al cacahuate')
    expect(avisos[0].detail).toContain('WK-0000001')
  })
})
