import { beforeEach, describe, expect, it, vi } from 'vitest'
import QRCode from 'qrcode'

import { reimprimirComprobante, type ComprobanteEstanciaDto } from '@/api/onboardingClient'
import {
  datosDeReimpresion,
  reimprimirComprobanteEstancia,
} from '@/services/comprobanteEstanciaService'

vi.mock('@/api/onboardingClient', () => ({ reimprimirComprobante: vi.fn() }))
vi.mock('qrcode', () => ({
  default: { toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,qr') },
}))

const DTO: ComprobanteEstanciaDto = {
  registroId: '9cb10500-4da3-40a8-881d-8b16064c25e0',
  codigoAccesoPadres: 'codigo-nuevo',
  sucursal: 'Zapopan Plaza Patria',
  cajero: 'Diego',
  tutor: 'Laura Méndez',
  telefono: '3311112222',
  entrada: '2026-10-03T18:00:00Z',
  total: 520,
  ninos: [
    {
      nombre: 'Santiago',
      edad: 5,
      notas: 'Alérgico al cacahuate',
      pulsera: 'WK-0000001',
      horas: 2,
      salidaEsperada: '2026-10-03T20:00:00Z',
    },
    {
      nombre: 'Regina',
      edad: 7,
      notas: null,
      pulsera: 'WK-0000002',
      horas: 3,
      salidaEsperada: '2026-10-03T21:00:00Z',
    },
  ],
}

describe('reimpresión del comprobante', () => {
  beforeEach(() => {
    vi.mocked(reimprimirComprobante).mockReset()
    vi.mocked(QRCode.toDataURL).mockClear()
  })

  it('arma el ticket con la salida más tardía y las notas de cada niño', () => {
    const datos = datosDeReimpresion(DTO, 'qr')
    expect(datos.reimpresion).toBe(true)
    expect(datos.ninos).toEqual([
      { nombre: 'Santiago', edad: 5, notas: 'Alérgico al cacahuate' },
      { nombre: 'Regina', edad: 7, notas: null },
    ])
    expect(datos.salidaEstimada).toBe(
      new Date('2026-10-03T21:00:00Z').toLocaleTimeString('es-MX', {
        hour: '2-digit',
        minute: '2-digit',
      }),
    )
    expect(datos.total).toBe(520)
  })

  it('el QR lleva el código nuevo que devuelve el backend, no el registroId', async () => {
    vi.mocked(reimprimirComprobante).mockResolvedValue(DTO)

    const datos = await reimprimirComprobanteEstancia(DTO.registroId)

    expect(reimprimirComprobante).toHaveBeenCalledWith(DTO.registroId)
    const url = vi.mocked(QRCode.toDataURL).mock.calls[0][0] as unknown as string
    expect(url).toBe(`${window.location.origin}/padres/access?code=codigo-nuevo`)
    expect(url).not.toContain(DTO.registroId)
    expect(datos.qrCodeUrl).toBe('data:image/png;base64,qr')
  })

  it('si el servidor responde sin la lista de niños, avisa con un mensaje claro', async () => {
    vi.mocked(reimprimirComprobante).mockResolvedValue({} as ComprobanteEstanciaDto)
    await expect(reimprimirComprobanteEstancia('reg-1')).rejects.toThrow(
      'El servidor devolvió un comprobante incompleto',
    )
    expect(QRCode.toDataURL).not.toHaveBeenCalled()
  })

  it('si falta el código del portal de padres tampoco arma el comprobante', async () => {
    vi.mocked(reimprimirComprobante).mockResolvedValue({
      ...DTO,
      codigoAccesoPadres: '',
    })
    await expect(reimprimirComprobanteEstancia('reg-1')).rejects.toThrow('incompleto')
  })
})
