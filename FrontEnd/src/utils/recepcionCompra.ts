import type { RecibirCompraRequest } from '@/types/compra'

/** Una línea del diálogo "Recibir compra". `ahora` es lo que el usuario
 * captura para esta vuelta (puede quedar vacío si borra el campo). */
export interface LineaRecepcionUI {
  detalle_id: string
  insumo_nombre: string
  unidad: string
  pedido: number
  recibido: number
  pendiente: number
  ahora: number | string | null
}

/** Cantidad capturada como número; vacío, inválido o negativo cuenta como 0. */
export function cantidadCapturada(l: Pick<LineaRecepcionUI, 'ahora'>): number {
  const n = Number(l.ahora)
  return Number.isFinite(n) && n > 0 ? n : 0
}

export function lineaExcedida(l: LineaRecepcionUI): boolean {
  return cantidadCapturada(l) > l.pendiente
}

/** Payload de `POST /compras/{id}/recibir`.
 *
 * Se mandan TODAS las líneas, incluidas las que quedan en 0. Antes se
 * filtraban las de 0 y el backend interpretaba "línea ausente" como "recibe
 * todo lo pendiente", así que la línea que el usuario dejaba en 0 se recibía
 * completa. El backend ahora también trata la ausente como 0, pero el payload
 * explícito deja clara la intención. */
export function armarRecepcion(lineas: LineaRecepcionUI[]): RecibirCompraRequest {
  return {
    lineas: lineas.map((l) => ({
      detalle_id: l.detalle_id,
      cantidad: String(cantidadCapturada(l)),
    })),
  }
}
