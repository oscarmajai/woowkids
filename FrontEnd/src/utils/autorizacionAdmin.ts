/**
 * Cancelar una orden ya pagada exige la autorización con PIN de un
 * administrador de la sucursal. El backend lo pide respondiendo 403 con
 * `code: AUTORIZACION_ADMIN_REQUERIDA` y el `turno_id` (turno abierto de quien
 * cancela) para el que hay que validar el PIN en /turnos-caja/validar-pin-admin.
 */
export const CODIGO_AUTORIZACION_ADMIN = 'AUTORIZACION_ADMIN_REQUERIDA'

/**
 * Devuelve el `turno_id` si el error es la petición de autorización del
 * administrador; `null` para cualquier otro error.
 */
export function turnoParaAutorizacion(error: unknown): string | null {
  if (typeof error !== 'object' || error === null) return null
  const { code, details } = error as { code?: unknown; details?: unknown }
  if (code !== CODIGO_AUTORIZACION_ADMIN) return null
  if (typeof details !== 'object' || details === null) return null
  const turnoId = (details as { turno_id?: unknown }).turno_id
  return typeof turnoId === 'string' && turnoId ? turnoId : null
}
