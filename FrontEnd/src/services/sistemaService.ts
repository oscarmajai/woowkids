import { sistemaApi } from '@/api/sistemaApi'
import type { EstadoRespaldos } from '@/types/sistema'

export const sistemaService = {
  async estadoRespaldos(): Promise<EstadoRespaldos> {
    return sistemaApi.estadoRespaldos()
  },
}
