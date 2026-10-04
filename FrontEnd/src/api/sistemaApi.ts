import { apiClient } from '@/api/axiosClient'
import type { EstadoRespaldos } from '@/types/sistema'

interface BackendRespaldo {
  inicio: string
  exitoso: boolean
}

interface BackendEstadoRespaldos {
  alerta: boolean
  mensaje: string | null
  ultimo_exitoso: BackendRespaldo | null
}

export const sistemaApi = {
  async estadoRespaldos(): Promise<EstadoRespaldos> {
    const { data } = await apiClient.get<BackendEstadoRespaldos>('/sistema/respaldos')
    return {
      alerta: data.alerta,
      mensaje: data.mensaje,
      ultimoExitoso: data.ultimo_exitoso?.inicio ?? null,
    }
  },
}
