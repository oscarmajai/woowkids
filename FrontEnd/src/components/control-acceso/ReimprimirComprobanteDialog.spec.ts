import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BaseDialog from '@/components/ui/BaseDialog.vue'
import ReimprimirComprobanteDialog from './ReimprimirComprobanteDialog.vue'
import { reimprimirComprobanteEstancia } from '@/services/comprobanteEstanciaService'
import { printTicketElement } from '@/utils/ticketPrinting'

vi.mock('@/services/comprobanteEstanciaService', () => ({
  reimprimirComprobanteEstancia: vi.fn(),
}))
vi.mock('@/utils/ticketPrinting', () => ({ printTicketElement: vi.fn() }))

const DATOS = {
  sucursal: 'Zapopan',
  cajero: 'Diego',
  fecha: new Date('2026-10-03T18:00:00Z'),
  tutor: 'Laura Méndez',
  telefono: '3311112222',
  ninos: [{ nombre: 'Santiago', edad: 5, notas: 'Alérgico al cacahuate' }],
  salidaEstimada: '14:00',
  total: 520,
  qrCodeUrl: 'data:image/png;base64,qr',
  reimpresion: true,
}

const montar = () =>
  mount(ReimprimirComprobanteDialog, {
    props: { modelValue: true, registroId: 'r1' },
    global: { stubs: { QDialog: { template: '<div><slot /></div>' } } },
  })

describe('ReimprimirComprobanteDialog (N5)', () => {
  beforeEach(() => {
    vi.mocked(reimprimirComprobanteEstancia).mockReset()
    vi.mocked(printTicketElement).mockReset()
  })

  it('no pide un código nuevo hasta que el cajero confirma', async () => {
    montar()
    await flushPromises()
    expect(reimprimirComprobanteEstancia).not.toHaveBeenCalled()
  })

  it('al confirmar emite el código nuevo, pinta el ticket con las notas e imprime', async () => {
    vi.mocked(reimprimirComprobanteEstancia).mockResolvedValue(DATOS)
    const wrapper = montar()

    wrapper.findComponent(BaseDialog).vm.$emit('confirm')
    await flushPromises()

    expect(reimprimirComprobanteEstancia).toHaveBeenCalledWith('r1')
    expect(wrapper.text()).toContain('REIMPRESIÓN')
    expect(wrapper.find('.ticket-notes').text()).toContain('Alérgico al cacahuate')
    expect(printTicketElement).toHaveBeenCalledTimes(1)
    expect(vi.mocked(printTicketElement).mock.calls[0][0]).toBeInstanceOf(HTMLElement)

    // Volver a imprimir no genera otro código.
    wrapper.findComponent(BaseDialog).vm.$emit('confirm')
    await flushPromises()
    expect(reimprimirComprobanteEstancia).toHaveBeenCalledTimes(1)
    expect(printTicketElement).toHaveBeenCalledTimes(2)
  })

  it('muestra el error del backend (p. ej. el niño ya salió)', async () => {
    vi.mocked(reimprimirComprobanteEstancia).mockRejectedValue({
      statusCode: 409,
      code: 'REGISTRO_NO_ACTIVO',
      message: 'El registro ya no tiene niños en estancia; no se puede reimprimir su comprobante.',
    })
    const wrapper = montar()

    wrapper.findComponent(BaseDialog).vm.$emit('confirm')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('ya no tiene niños en estancia')
    expect(printTicketElement).not.toHaveBeenCalled()
  })
})
