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

  async crear(payload: CrearComandaRequest, signal?: AbortSignal): Promise<Comanda> {
    const { data } = await apiClient.post<Comanda>('/comandas', payload, { signal })
    return data
  },

  async modificarDetalles(
    comandaId: string,
    detallesIdsAEliminar: string[],
    motivoCancelacion?: string,
    signal?: AbortSignal,
  ): Promise<Comanda> {
    const { data } = await apiClient.patch<Comanda>(
      `/comandas/${comandaId}/detalles`,
      {
        detalles_ids_a_eliminar: detallesIdsAEliminar,
        ...(motivoCancelacion ? { motivo_cancelacion: motivoCancelacion } : {}),
      },
      { signal },
    )
    return data
  },
}
