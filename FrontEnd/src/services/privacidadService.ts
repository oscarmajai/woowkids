import { privacidadApi } from '@/api/privacidadApi'
import type {
  AvisoPrivacidad,
  AvisoPrivacidadAdmin,
  PublicarAvisoPayload,
} from '@/types/privacidad'

export const privacidadService = {
  obtenerVigente(): Promise<AvisoPrivacidad> {
    return privacidadApi.obtenerVigente()
  },

  obtenerAdmin(): Promise<AvisoPrivacidadAdmin> {
    return privacidadApi.obtenerAdmin()
  },

  /** Publica una versión nueva; solo manda los textos si cambiaron. */
  publicar(
    actual: AvisoPrivacidadAdmin,
    cambios: Omit<PublicarAvisoPayload, 'versionBase'>,
  ): Promise<AvisoPrivacidadAdmin> {
    const textoIntegral =
      cambios.textoIntegral !== undefined && cambios.textoIntegral !== actual.textoIntegral
        ? cambios.textoIntegral
        : undefined
    const textoSimplificado =
      cambios.textoSimplificado !== undefined &&
      cambios.textoSimplificado !== actual.textoSimplificado
        ? cambios.textoSimplificado
        : undefined
    return privacidadApi.publicar({
      versionBase: actual.version,
      responsable: cambios.responsable,
      textoIntegral,
      textoSimplificado,
      motivoCambio: cambios.motivoCambio?.trim() || undefined,
    })
  },
}
