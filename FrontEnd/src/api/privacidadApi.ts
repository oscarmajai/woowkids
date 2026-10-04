import { apiClient, normalizeAxiosError, rawApiClient } from '@/api/axiosClient'
import type {
  AvisoPrivacidad,
  AvisoPrivacidadAdmin,
  PublicarAvisoPayload,
  ResponsableAviso,
  VersionAviso,
} from '@/types/privacidad'

interface BackendAvisoPublico {
  version: number
  vigente_desde: string
  fecha_vigencia: string
  nombre_comercial: string
  texto_integral: string
  texto_simplificado: string
}

interface BackendResponsable {
  razon_social: string
  nombre_comercial: string
  domicilio: string
  area_datos_personales: string
  correo_datos_personales: string
  telefono_datos_personales: string
  url_aviso: string
  dias_conservacion_imagenes: number
  anios_conservacion_registros: number
}

interface BackendVersion {
  version: number
  vigente_desde: string
  publicado_por: string | null
  motivo_cambio: string | null
}

interface BackendAvisoAdmin extends BackendVersion {
  responsable: BackendResponsable
  texto_integral: string
  texto_simplificado: string
  marcadores: Record<string, string>
  pendientes: string[]
  historial: BackendVersion[]
}

function aResponsable(r: BackendResponsable): ResponsableAviso {
  return {
    razonSocial: r.razon_social,
    nombreComercial: r.nombre_comercial,
    domicilio: r.domicilio,
    areaDatosPersonales: r.area_datos_personales,
    correoDatosPersonales: r.correo_datos_personales,
    telefonoDatosPersonales: r.telefono_datos_personales,
    urlAviso: r.url_aviso,
    diasConservacionImagenes: r.dias_conservacion_imagenes,
    aniosConservacionRegistros: r.anios_conservacion_registros,
  }
}

function deResponsable(r: ResponsableAviso): BackendResponsable {
  return {
    razon_social: r.razonSocial,
    nombre_comercial: r.nombreComercial,
    domicilio: r.domicilio,
    area_datos_personales: r.areaDatosPersonales,
    correo_datos_personales: r.correoDatosPersonales,
    telefono_datos_personales: r.telefonoDatosPersonales,
    url_aviso: r.urlAviso,
    dias_conservacion_imagenes: r.diasConservacionImagenes,
    anios_conservacion_registros: r.aniosConservacionRegistros,
  }
}

function aVersion(v: BackendVersion): VersionAviso {
  return {
    version: v.version,
    vigenteDesde: v.vigente_desde,
    publicadoPor: v.publicado_por,
    motivoCambio: v.motivo_cambio,
  }
}

function aAdmin(data: BackendAvisoAdmin): AvisoPrivacidadAdmin {
  return {
    ...aVersion(data),
    responsable: aResponsable(data.responsable),
    textoIntegral: data.texto_integral,
    textoSimplificado: data.texto_simplificado,
    marcadores: data.marcadores,
    pendientes: data.pendientes,
    historial: data.historial.map(aVersion),
  }
}

export const privacidadApi = {
  /**
   * Público: la página /aviso-de-privacidad y el portal de padres no tienen
   * sesión de personal. rawApiClient (sin interceptor) para que un 401 nunca
   * dispare un refresh ni cierre una sesión.
   */
  async obtenerVigente(): Promise<AvisoPrivacidad> {
    try {
      const { data } = await rawApiClient.get<BackendAvisoPublico>('/privacidad/aviso')
      return {
        version: data.version,
        vigenteDesde: data.vigente_desde,
        fechaVigencia: data.fecha_vigencia,
        nombreComercial: data.nombre_comercial,
        textoIntegral: data.texto_integral,
        textoSimplificado: data.texto_simplificado,
      }
    } catch (err) {
      throw normalizeAxiosError(err)
    }
  },

  async obtenerAdmin(): Promise<AvisoPrivacidadAdmin> {
    const { data } = await apiClient.get<BackendAvisoAdmin>('/privacidad/admin/aviso')
    return aAdmin(data)
  },

  async publicar(payload: PublicarAvisoPayload): Promise<AvisoPrivacidadAdmin> {
    const { data } = await apiClient.post<BackendAvisoAdmin>('/privacidad/admin/aviso', {
      version_base: payload.versionBase,
      responsable: deResponsable(payload.responsable),
      texto_integral: payload.textoIntegral,
      texto_simplificado: payload.textoSimplificado,
      motivo_cambio: payload.motivoCambio,
    })
    return aAdmin(data)
  },
}
