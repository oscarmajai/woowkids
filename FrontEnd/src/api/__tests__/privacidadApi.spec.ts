import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
const rawGet = vi.fn()
vi.mock('@/api/axiosClient', () => ({
  apiClient: { get: apiGet, post: apiPost },
  rawApiClient: { get: rawGet },
  normalizeAxiosError: (err: unknown) => ({ statusCode: 0, code: 'X', message: String(err) }),
}))

const { privacidadApi } = await import('@/api/privacidadApi')

const RESPONSABLE = {
  razon_social: 'Diversión SA',
  nombre_comercial: 'Woow Kids',
  domicilio: 'Av. 1',
  area_datos_personales: 'Datos Personales',
  correo_datos_personales: 'arco@woow.mx',
  telefono_datos_personales: '3312345678',
  url_aviso: 'https://woow.mx/aviso-de-privacidad',
  dias_conservacion_imagenes: 90,
  anios_conservacion_registros: 5,
}

describe('privacidadApi', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    rawGet.mockReset()
  })

  it('el aviso vigente se pide sin sesión (cliente sin interceptor)', async () => {
    rawGet.mockResolvedValue({
      data: {
        version: 2,
        vigente_desde: '2026-10-03T18:00:00Z',
        fecha_vigencia: '2026-10-03',
        nombre_comercial: 'Woow Kids',
        texto_integral: '# Integral',
        texto_simplificado: '# Simplificado',
      },
    })

    const aviso = await privacidadApi.obtenerVigente()

    expect(rawGet).toHaveBeenCalledWith('/privacidad/aviso')
    expect(apiGet).not.toHaveBeenCalled()
    expect(aviso).toEqual({
      version: 2,
      vigenteDesde: '2026-10-03T18:00:00Z',
      fechaVigencia: '2026-10-03',
      nombreComercial: 'Woow Kids',
      textoIntegral: '# Integral',
      textoSimplificado: '# Simplificado',
    })
  })

  it('publica con los nombres del contrato del backend', async () => {
    apiPost.mockResolvedValue({
      data: {
        version: 3,
        vigente_desde: '2026-10-04T00:00:00Z',
        publicado_por: 'Sistema',
        motivo_cambio: 'Domicilio',
        responsable: RESPONSABLE,
        texto_integral: 'a',
        texto_simplificado: 'b',
        marcadores: { razon_social: 'Razón social' },
        pendientes: [],
        historial: [
          { version: 3, vigente_desde: 'x', publicado_por: 'Sistema', motivo_cambio: null },
        ],
      },
    })

    const admin = await privacidadApi.publicar({
      versionBase: 2,
      responsable: {
        razonSocial: 'Diversión SA',
        nombreComercial: 'Woow Kids',
        domicilio: 'Av. 1',
        areaDatosPersonales: 'Datos Personales',
        correoDatosPersonales: 'arco@woow.mx',
        telefonoDatosPersonales: '3312345678',
        urlAviso: 'https://woow.mx/aviso-de-privacidad',
        diasConservacionImagenes: 90,
        aniosConservacionRegistros: 5,
      },
      motivoCambio: 'Domicilio',
    })

    expect(apiPost).toHaveBeenCalledWith('/privacidad/admin/aviso', {
      version_base: 2,
      responsable: RESPONSABLE,
      texto_integral: undefined,
      texto_simplificado: undefined,
      motivo_cambio: 'Domicilio',
    })
    expect(admin.version).toBe(3)
    expect(admin.responsable.correoDatosPersonales).toBe('arco@woow.mx')
    expect(admin.historial[0]).toEqual({
      version: 3,
      vigenteDesde: 'x',
      publicadoPor: 'Sistema',
      motivoCambio: null,
    })
  })
})
