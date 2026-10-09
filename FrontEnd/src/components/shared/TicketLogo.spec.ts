import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import TicketLogo from './TicketLogo.vue'

describe('TicketLogo', () => {
  it('usa por defecto el logo de 80 mm, de 46 mm de ancho', () => {
    const img = mount(TicketLogo).get('img')
    expect(img.attributes('src')).toBe('/ticket-logo-80.png')
    expect(img.attributes('style')).toContain('46mm')
    expect(img.attributes('alt')).toBe('Woow Kids')
  })

  it('usa el logo chico en rollo de 58 mm', () => {
    const img = mount(TicketLogo, { props: { anchoMm: 58 } }).get('img')
    expect(img.attributes('src')).toBe('/ticket-logo-58.png')
    expect(img.attributes('style')).toContain('34mm')
  })

  it('en A4 usa el logo de 80 mm', () => {
    expect(
      mount(TicketLogo, { props: { anchoMm: 210 } })
        .get('img')
        .attributes('src'),
    ).toBe('/ticket-logo-80.png')
  })

  it('si el archivo del logo no carga, se oculta para no bloquear la impresión', async () => {
    const wrapper = mount(TicketLogo)
    await wrapper.get('img').trigger('error')
    expect(wrapper.find('img').exists()).toBe(false)
  })
})
