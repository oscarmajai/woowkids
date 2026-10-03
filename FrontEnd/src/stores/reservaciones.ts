import { defineStore } from 'pinia'
import { mensajeDeError } from '@/utils/errorHandler'
import { reservacionesApi } from '@/api/reservacionesApi'
import type {
  Reservaciones,
  ReservacionesCreate,
  ReservacionesUpdate,
  Disponibilidad,
} from '@/types/reservaciones'
import type { ReservacionCompletaRequest } from '@/types/reservaciones_completa'

// Folio de la última carga pedida: si llega la respuesta de una carga anterior
// (p. ej. el calendario cambió de mes mientras esperaba), se descarta para no
// pintar otro rango ni encadenar recargas (A9).
let ultimaCarga = 0

interface ReservacionesState {
  reservaciones: Reservaciones[]
  loading: boolean
  error: string | null
  disponibilidad: Disponibilidad | null
  disponibilidadLoading: boolean
}

export const useReservacionesStore = defineStore('reservaciones', {
  state: (): ReservacionesState => ({
    reservaciones: [],
    loading: false,
    error: null,
    disponibilidad: null,
    disponibilidadLoading: false,
  }),
  getters: {
    activas: (state) => state.reservaciones.filter((r) => r.activo),
  },
  actions: {
    /**
     * `desde`/`hasta` (YYYY-MM-DD, ambos inclusive) acotan la carga al rango
     * visible del calendario -- las vistas Semana y Día de CalendarioPage.vue
     * los usan para no traer todo el histórico de la sucursal.
     */
    async cargar(sucursal_id?: string, desde?: string, hasta?: string) {
      const folio = ++ultimaCarga
      this.loading = true
      this.error = null
      try {
        const reservaciones = await reservacionesApi.listar(sucursal_id, desde, hasta)
        if (folio === ultimaCarga) this.reservaciones = reservaciones
      } catch (error: unknown) {
        if (folio === ultimaCarga) {
          this.error = mensajeDeError(error, 'Error al cargar reservaciones')
        }
      } finally {
        if (folio === ultimaCarga) this.loading = false
      }
    },
    async crearReservacion(body: ReservacionesCreate) {
      const nueva = await reservacionesApi.crear(body)
      this.reservaciones.push(nueva)
      return nueva
    },
    /**
     * Alta atómica (QA #10): reservación + extras + productos + pagos en una
     * sola transacción vía POST /reservaciones/completa. Reemplaza al loop de
     * requests sueltos que usaba NuevaReservacionPage.vue.
     */
    async crearReservacionCompleta(body: ReservacionCompletaRequest) {
      const resultado = await reservacionesApi.crearCompleta(body)
      this.reservaciones.push(resultado.reservacion)
      return resultado
    },
    async actualizarReservacion(id: string, body: ReservacionesUpdate) {
      const actualizada = await reservacionesApi.actualizar(id, body)
      const idx = this.reservaciones.findIndex((r) => r.id === id)
      if (idx !== -1) this.reservaciones[idx] = actualizada
      return actualizada
    },
    async eliminarReservacion(id: string) {
      await reservacionesApi.eliminar(id)
      this.reservaciones = this.reservaciones.filter((r) => r.id !== id)
    },
    /** Bloques de horario de la sucursal para una fecha, ocupados o libres
     * según las reservaciones no canceladas -- usado por el paso de fecha y
     * hora de NuevaReservacionPage.vue. */
    async cargarDisponibilidad(sucursalId: string, fecha: string) {
      this.disponibilidadLoading = true
      try {
        this.disponibilidad = await reservacionesApi.disponibilidad(sucursalId, fecha)
      } catch (error: unknown) {
        this.error = mensajeDeError(error, 'Error al cargar la disponibilidad')
        this.disponibilidad = null
      } finally {
        this.disponibilidadLoading = false
      }
    },
  },
})
