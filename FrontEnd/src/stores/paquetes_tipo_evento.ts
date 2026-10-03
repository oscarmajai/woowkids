import { defineStore } from 'pinia'
import { mensajeDeError } from '@/utils/errorHandler'
import { paquetesTipoEventoApi } from '@/api/paquetesTipoEventoApi'
import { diferenciaTipos } from '@/utils/paquetes'
import type {
  Paquetes_tipo_evento,
  Paquetes_tipo_evento_create,
} from '@/types/paquetes_tipo_evento'

interface PaquetesTipoEventoState {
  paquetes_tipo_evento: Paquetes_tipo_evento[]
  loading: boolean
  error: string | null
}

export const usePaquetesTipoEventoStore = defineStore('paquetes_tipo_evento', {
  state: (): PaquetesTipoEventoState => ({
    paquetes_tipo_evento: [],
    loading: false,
    error: null,
  }),
  getters: {},
  actions: {
    async fetchPorPaquete(paquete_id: string) {
      this.loading = true
      this.error = null
      try {
        this.paquetes_tipo_evento = await paquetesTipoEventoApi.listar(paquete_id)
      } catch (error: unknown) {
        this.error = mensajeDeError(error, 'Error al cargar tipos de evento del paquete')
      } finally {
        this.loading = false
      }
    },
    async crearPaqueteTipoEvento(body: Paquetes_tipo_evento_create) {
      const nuevo = await paquetesTipoEventoApi.crear(body)
      this.paquetes_tipo_evento.push(nuevo)
      return nuevo
    },
    async eliminarPaqueteTipoEvento(paquete_id: string, tipo_evento_id: string) {
      await paquetesTipoEventoApi.eliminar(paquete_id, tipo_evento_id)
      this.paquetes_tipo_evento = this.paquetes_tipo_evento.filter(
        (p) => !(p.paquete_id === paquete_id && p.tipo_evento_id === tipo_evento_id),
      )
    },
    /**
     * Deja al paquete con exactamente los tipos de evento `despues` (M17):
     * asocia los nuevos y desasocia los que se quitaron, partiendo de `antes`.
     */
    async sincronizar(paquete_id: string, antes: string[], despues: string[]) {
      const { agregar, quitar } = diferenciaTipos(antes, despues)
      for (const tipo_evento_id of agregar) {
        await this.crearPaqueteTipoEvento({ paquete_id, tipo_evento_id })
      }
      for (const tipo_evento_id of quitar) {
        await this.eliminarPaqueteTipoEvento(paquete_id, tipo_evento_id)
      }
    },
  },
})
