import { describe, expect, it } from 'vitest'
import { camaraEnPaginaDisponible, medidasReducidas } from '@/utils/fotos'

describe('fotos del registro', () => {
  it('reduce la foto del teléfono a 1280 px por el lado mayor', () => {
    expect(medidasReducidas(4032, 3024)).toEqual({ ancho: 1280, alto: 960 })
    expect(medidasReducidas(3024, 4032)).toEqual({ ancho: 960, alto: 1280 })
  })

  it('no agranda una foto pequeña', () => {
    expect(medidasReducidas(800, 600)).toEqual({ ancho: 800, alto: 600 })
  })

  it('sin getUserMedia (HTTP) usa la cámara del dispositivo o un archivo', () => {
    expect(camaraEnPaginaDisponible({} as Navigator)).toBe(false)
    expect(
      camaraEnPaginaDisponible({
        mediaDevices: { getUserMedia: () => null },
      } as unknown as Navigator),
    ).toBe(true)
  })
})
