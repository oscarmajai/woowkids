import { describe, expect, it } from 'vitest'
import { parsearAviso } from '@/utils/avisoPrivacidad'

describe('parsearAviso', () => {
  it('separa título, secciones, párrafos y viñetas', () => {
    const texto = [
      '# AVISO DE PRIVACIDAD INTEGRAL',
      '',
      'Versión 1.',
      '',
      '## 1. Responsable',
      '',
      'Primera línea',
      'del mismo párrafo.',
      '',
      '- Uno',
      '- Dos',
      'Después de la lista.',
    ].join('\n')

    expect(parsearAviso(texto)).toEqual([
      { tipo: 'titulo', texto: 'AVISO DE PRIVACIDAD INTEGRAL' },
      { tipo: 'parrafo', texto: 'Versión 1.' },
      { tipo: 'seccion', texto: '1. Responsable' },
      { tipo: 'parrafo', texto: 'Primera línea del mismo párrafo.' },
      { tipo: 'lista', items: ['Uno', 'Dos'] },
      { tipo: 'parrafo', texto: 'Después de la lista.' },
    ])
  })

  it('no interpreta HTML: el texto sale tal cual', () => {
    expect(parsearAviso('<b>hola</b>\r\n\r\n- <script>x</script>')).toEqual([
      { tipo: 'parrafo', texto: '<b>hola</b>' },
      { tipo: 'lista', items: ['<script>x</script>'] },
    ])
  })

  it('un texto vacío no produce bloques', () => {
    expect(parsearAviso('\n\n  \n')).toEqual([])
  })
})
