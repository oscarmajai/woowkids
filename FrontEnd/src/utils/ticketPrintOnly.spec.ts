import { afterEach, describe, expect, it } from 'vitest'

import { createTicketDocument } from './ticketPrinting'

describe('createTicketDocument · elementos solo para impresión', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  function montar(): HTMLElement {
    const raiz = document.createElement('div')
    raiz.innerHTML = `
      <p class="normal">Reporte</p>
      <div data-print-only class="logo" style="display: none">LOGO</div>
      <div class="oculto" style="display: none">NO SE IMPRIME</div>`
    document.body.append(raiz)
    return raiz
  }

  it('muestra en el papel lo marcado como data-print-only aunque en pantalla esté oculto', () => {
    const doc = createTicketDocument(montar(), 210)
    const logo = doc.querySelector<HTMLElement>('.logo')!
    expect(logo.style.display).toBe('block')
  })

  it('no muestra lo que está oculto sin la marca', () => {
    const doc = createTicketDocument(montar(), 210)
    expect(doc.querySelector<HTMLElement>('.oculto')!.style.display).toBe('none')
  })
})
