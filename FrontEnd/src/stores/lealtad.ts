import { defineStore } from 'pinia'
import {
  actualizarConfiguracionLealtad,
  ajustarPuntosLealtad,
  buscarClientesLealtad,
  exportarReporteLealtad,
  listarMovimientosLealtad,
  obtenerConfiguracionCanjeLealtad,
  obtenerConfiguracionLealtad,
  obtenerReporteLealtad,
  obtenerSaldoLealtad,
} from '@/services/lealtadService'
import { mensajeDeError } from '@/utils/errorHandler'
import type { ApiError } from '@/types/auth'
import type {
  AjustePuntosInput,
  ClienteLealtad,
  ConfiguracionCanje,
  ConfiguracionLealtad,
  ConfiguracionLealtadInput,
  MovimientoPuntos,
  ReporteLealtad,
  SaldoPuntos,
} from '@/types/lealtad'

interface LealtadState {
  configuracion: ConfiguracionLealtad | null
  saldo: SaldoPuntos | null
  movimientos: MovimientoPuntos[]
  reporte: ReporteLealtad | null
  clientes: ClienteLealtad[]
  loading: boolean
  error: string | null
}

export const useLealtadStore = defineStore('lealtad', {
  state: (): LealtadState => ({
    configuracion: null,
    saldo: null,
    movimientos: [],
    reporte: null,
    clientes: [],
    loading: false,
    error: null,
  }),
  actions: {
    async cargarConfiguracion(sucursalId: string) {
      this.loading = true
      this.error = null
      try {
        this.configuracion = await obtenerConfiguracionLealtad(sucursalId)
      } catch (error: unknown) {
        const apiError = error as ApiError
        if (apiError.statusCode === 404) {
          this.configuracion = null
        } else {
          this.error = mensajeDeError(apiError, 'Error al cargar la configuración de lealtad')
        }
      } finally {
        this.loading = false
      }
    },
    /**
     * Valor del punto y mínimo de canje de la sucursal, para cobrar (A6). Usa
     * el endpoint de solo lectura que permite `lealtad:redimir`: el de
     * `configuracion` exige el permiso de configurar y al cajero le da 403.
     * Igual que `cargarSaldo`, devuelve el dato sin guardarlo en el estado y
     * deja pasar el error para que quien cobra deshabilite el canje.
     */
    async cargarConfiguracionCanje(sucursalId: string): Promise<ConfiguracionCanje> {
      return obtenerConfiguracionCanjeLealtad(sucursalId)
    },
    async guardarConfiguracion(sucursalId: string, body: ConfiguracionLealtadInput) {
      this.configuracion = await actualizarConfiguracionLealtad(sucursalId, body)
      return this.configuracion
    },
    /**
     * Consulta el saldo de un celular y lo devuelve sin escribirlo en
     * `this.saldo`: ese estado pertenece al kardex y una consulta tardía desde
     * el modal de pago no debe pisar (ni dejar) el saldo de otro cliente.
     */
    async cargarSaldo(sucursalId: string, celular: string): Promise<SaldoPuntos> {
      return obtenerSaldoLealtad(sucursalId, celular)
    },
    async cargarMovimientos(sucursalId: string, celular: string, desde?: string, hasta?: string) {
      this.loading = true
      this.error = null
      try {
        this.movimientos = await listarMovimientosLealtad(sucursalId, celular, desde, hasta)
        this.saldo = await obtenerSaldoLealtad(sucursalId, celular)
      } catch (error: unknown) {
        this.error = mensajeDeError(error, 'Error al cargar el kardex de lealtad')
      } finally {
        this.loading = false
      }
    },
    async cargarReporte(sucursalId: string, desde?: string, hasta?: string) {
      this.loading = true
      this.error = null
      try {
        this.reporte = await obtenerReporteLealtad(sucursalId, desde, hasta)
      } catch (error: unknown) {
        this.error = mensajeDeError(error, 'Error al cargar el reporte de lealtad')
      } finally {
        this.loading = false
      }
    },
    async exportarReporte(sucursalId: string, desde?: string, hasta?: string) {
      await exportarReporteLealtad(sucursalId, desde, hasta)
    },
    async buscarClientes(sucursalId: string, q: string) {
      if (!q) {
        this.clientes = []
        return
      }
      try {
        this.clientes = await buscarClientesLealtad(sucursalId, q)
      } catch (error: unknown) {
        this.error = mensajeDeError(error, 'Error al buscar clientes de lealtad')
      }
    },
    async ajustarPuntos(sucursalId: string, body: AjustePuntosInput) {
      const movimiento = await ajustarPuntosLealtad(sucursalId, body)
      if (this.saldo?.celular === body.celular) {
        this.saldo = { ...this.saldo, saldo: movimiento.saldo_resultante }
      }
      if (this.movimientos.length && this.movimientos[0]?.celular === body.celular) {
        this.movimientos = [movimiento, ...this.movimientos]
      }
      return movimiento
    },
  },
})
