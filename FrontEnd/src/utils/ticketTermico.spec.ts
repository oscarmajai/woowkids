import { describe, expect, it } from 'vitest'

import { ajustesTermicos, TAMANO_MINIMO_TERMICO_PX } from './ticketPrinting'

const base = {
  fontSize: '14px',
  fontWeight: '700',
  color: 'rgb(0, 0, 0)',
  backgroundColor: 'rgba(0, 0, 0, 0)',
}

describe('ajustesTermicos', () => {
  it('imprime todo el texto en negro, sin grises', () => {
    expect(ajustesTermicos({ ...base, color: 'rgb(102, 102, 102)' }).color).toBe('#000')
  })

  it('también fuerza el color con el que Chromium pinta el texto', () => {
    // Si solo cambia `color`, el -webkit-text-fill-color copiado del original
    // (gris) gana al pintar y el texto sale tenue en el papel.
    const cambios = ajustesTermicos({ ...base, color: 'rgb(148, 163, 184)' })
    expect(cambios['-webkit-text-fill-color']).toBe('#000')
    expect(cambios['text-decoration-color']).toBe('#000')
  })

  it('sube el texto menor al mínimo legible', () => {
    const cambios = ajustesTermicos({ ...base, fontSize: '9px' })
    expect(cambios['font-size']).toBe(`${TAMANO_MINIMO_TERMICO_PX}px`)
  })

  it('no toca el texto que ya es legible', () => {
    expect(ajustesTermicos({ ...base, fontSize: '13px' })['font-size']).toBeUndefined()
  })

  it('refuerza el peso normal del texto chico y respeta los títulos grandes', () => {
    expect(ajustesTermicos({ ...base, fontSize: '11px', fontWeight: '400' })['font-weight']).toBe(
      '600',
    )
    expect(ajustesTermicos({ ...base, fontSize: '22px', fontWeight: '400' })['font-weight']).toBe(
      undefined,
    )
  })

  it('cambia un fondo de color por un contorno negro', () => {
    const cambios = ajustesTermicos({ ...base, backgroundColor: 'rgba(2, 95, 224, 0.08)' })
    expect(cambios['background-color']).toBe('transparent')
    expect(cambios.outline).toBe('1px solid #000')
  })

  it('deja sin contorno los fondos blancos o transparentes', () => {
    expect(
      ajustesTermicos({ ...base, backgroundColor: 'rgb(255, 255, 255)' }).outline,
    ).toBeUndefined()
    expect(ajustesTermicos(base).outline).toBeUndefined()
  })
})
