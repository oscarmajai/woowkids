import { apiClient } from '@/api/axiosClient'
import type { Comanda, CrearComandaRequest, EstadoActualComanda } from '@/types/comanda'

export const comandasApi = {
  async listar(signal?: AbortSignal): Promise<Comanda[]> {
    const { data } = await apiClient.get<Comanda[]>('/comandas', { signal })
    return data
  },

  /**
   * Avanza el estado (P → E → L → T) o cancela (C, desde P/E/L). El backend
   * responde 409 a una transición inválida. Cancelar una comanda pagada exige
   * `tokenPinAdmin` (de /turnos-caja/validar-pin-admin): sin él responde 403
   * AUTORIZACION_ADMIN_REQUERIDA con el `turno_id` para pedir el PIN.
   */
  async cambiarEstado(
    comandaId: string,
    nuevoEstado: EstadoActualComanda,
    opciones: { motivoCancelacion?: string; tokenPinAdmin?: string } = {},
    signal?: AbortSignal,
  ): Promise<void> {
    const { motivoCancelacion, tokenPinAdmin } = opciones
    await apiClient.patch(
      `/comandas/${comandaId}/estado`,
      {
        estado_actual: nuevoEstado,
        ...(motivoCancelacion ? { motivo_cancelacion: motivoCancelacion } : {}),
        ...(tokenPinAdmin ? { token_pin_admin: tokenPinAdmin } : {}),
      },
      { signal },
    )
  },

  /**
   * Devuelve al cliente el dinero de una comanda ya entregada (T), sin
   * regresar su stock. Como la cancelación de una pagada: sin `tokenPinAdmin`
   * el backend responde 403 AUTORIZACION_ADMIN_REQUERIDA con el `turno_id`
   * para pedir el PIN; 409 DEVOLUCION_NO_APLICA si no está entregada o ya se
   * devolvió.
   */
  async devolver(
    comandaId: string,
    motivo: string,
    tokenPinAdmin?: string,
    signal?: AbortSignal,
  ): Promise<void> {
    await apiClient.post(
      `/comandas/${comandaId}/devolucion`,
      { motivo, ...(tokenPinAdmin ? { token_pin_admin: tokenPinAdmin } : {}) },
      { signal },
    )
  },

  async crear(payload: CrearComandaRequest, signal?: AbortSignal): Promise<Comanda> {
    const { data } = await apiClient.post<Comanda>('/comandas', payload, { signal })
    return data
  },

  /**
   * Quita productos de una comanda pendiente. Con `modificadoEsperado` (el
   * `modificado` de GET /pagos/detalles/comanda/{id}) el backend responde 409
   * COMANDA_MODIFICADA si la orden cambió desde que se leyó.
   */
  async modificarDetalles(
    comandaId: string,
    detallesIdsAEliminar: string[],
    motivoCancelacion?: string,
    signal?: AbortSignal,
    modificadoEsperado?: string,
  ): Promise<Comanda> {
    const { data } = await apiClient.patch<Comanda>(
      `/comandas/${comandaId}/detalles`,
      {
        detalles_ids_a_eliminar: detallesIdsAEliminar,
        ...(motivoCancelacion ? { motivo_cancelacion: motivoCancelacion } : {}),
        ...(modificadoEsperado ? { modificado_esperado: modificadoEsperado } : {}),
      },
      { signal },
    )
    return data
  },
}
