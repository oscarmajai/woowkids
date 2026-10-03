import { comandasApi } from '@/api/comandasApi'
import type { Comanda, CrearComandaRequest, EstadoActualComanda } from '@/types/comanda'

export async function obtenerComandas(signal?: AbortSignal): Promise<Comanda[]> {
  return comandasApi.listar(signal)
}

export async function cambiarEstadoComanda(
  comandaId: string,
  nuevoEstado: EstadoActualComanda,
  signal?: AbortSignal,
): Promise<void> {
  return comandasApi.cambiarEstado(comandaId, nuevoEstado, {}, signal)
}

/**
 * Cancela la comanda con su motivo. Si está pagada, el backend exige el token
 * de PIN de un administrador (ver useCancelarComanda).
 */
export async function cancelarComanda(
  comandaId: string,
  motivoCancelacion: string,
  tokenPinAdmin?: string,
): Promise<void> {
  return comandasApi.cambiarEstado(comandaId, 'C', { motivoCancelacion, tokenPinAdmin })
}

export async function crearComanda(
  payload: CrearComandaRequest,
  signal?: AbortSignal,
): Promise<Comanda> {
  return comandasApi.crear(payload, signal)
}

export async function modificarDetallesComanda(
  comandaId: string,
  detallesIdsAEliminar: string[],
  motivoCancelacion?: string,
  signal?: AbortSignal,
): Promise<Comanda> {
  return comandasApi.modificarDetalles(comandaId, detallesIdsAEliminar, motivoCancelacion, signal)
}
