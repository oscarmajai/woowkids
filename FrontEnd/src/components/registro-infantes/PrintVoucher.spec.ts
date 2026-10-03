import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import QRCode from 'qrcode'

import PrintVoucher from './PrintVoucher.vue'
import { useRegistrationStore } from '@/stores/registration'

vi.mock('qrcode', () => ({
  default: { toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,qr') },
}))

vi.mock('@/utils/ticketPrinting', () => ({
  printTicketElement: vi.fn(),
}))

function montarCon(registroId: string, codigoAccesoPadres: string) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useRegistrationStore()
  store.registroId = registroId
  store.codigoAccesoPadres = codigoAccesoPadres
  return mount(PrintVoucher, { global: { plugins: [pinia] } })
}

describe('PrintVoucher: QR del portal de padres (A17)', () => {
  beforeEach(() => {
    vi.mocked(QRCode.toDataURL).mockClear()
  })

  it('el QR lleva el código opaco del portal, nunca el registroId', async () => {
    montarCon('9cb10500-4da3-40a8-881d-8b16064c25e0', 'v0mSa2NAjDJTGs1R-yiCc_fkJwsN9W')
    await flushPromises()

    expect(QRCode.toDataURL).toHaveBeenCalledTimes(1)
    const url = vi.mocked(QRCode.toDataURL).mock.calls[0][0] as string
    expect(url).toBe(`${window.location.origin}/padres/access?code=v0mSa2NAjDJTGs1R-yiCc_fkJwsN9W`)
    expect(url).not.toContain('9cb10500-4da3-40a8-881d-8b16064c25e0')
  })

  it('sin código de acceso no genera QR (no cae al registroId)', async () => {
    const wrapper = montarCon('9cb10500-4da3-40a8-881d-8b16064c25e0', '')
    await flushPromises()

    expect(QRCode.toDataURL).not.toHaveBeenCalled()
    expect(wrapper.find('img.qr-code').exists()).toBe(false)
  })
})
