import type { ItemTicket } from '@/components/comandas/TicketItem.vue'

/**
 * Pedido del POS en curso guardado en sessionStorage (por pestaña), para que
 * recargar la página a mitad de una venta no lo pierda. No guarda pagos: el
 * cobro se vuelve a capturar. La clave de idempotencia sí, para que un cobro
 * que quedó en el aire no se registre dos veces al reintentarlo.
 */
export interface PedidoEnCurso {
  version: 1
  guardado: string
  items: ItemTicket[]
  nombreCliente: string
  mesa: string
  idempotencyKey: string | null
}

const PREFIJO = 'wk:pos:pedido-en-curso'

export function clavePedidoEnCurso(usuarioId: string | null, sucursalId: string | null): string {
  return `${PREFIJO}:${usuarioId ?? 'anon'}:${sucursalId ?? 'sin-sucursal'}`
}

function almacen(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage : null
  } catch {
    return null
  }
}

export function guardarPedidoEnCurso(
  clave: string,
  pedido: Omit<PedidoEnCurso, 'version' | 'guardado'>,
): void {
  const s = almacen()
  if (!s) return
  try {
    if (pedido.items.length === 0) {
      s.removeItem(clave)
      return
    }
    const dato: PedidoEnCurso = { version: 1, guardado: new Date().toISOString(), ...pedido }
    s.setItem(clave, JSON.stringify(dato))
  } catch {
    // Sin espacio o almacenamiento bloqueado: el pedido sigue en memoria.
  }
}

function esPedido(valor: unknown): valor is PedidoEnCurso {
  if (typeof valor !== 'object' || valor === null) return false
  const v = valor as Partial<PedidoEnCurso>
  return (
    v.version === 1 &&
    Array.isArray(v.items) &&
    v.items.every(
      (i) =>
        typeof i === 'object' &&
        i !== null &&
        typeof i.id === 'string' &&
        typeof i.cantidad === 'number' &&
        typeof i.producto?.id === 'string',
    ) &&
    typeof v.nombreCliente === 'string' &&
    typeof v.mesa === 'string'
  )
}

/** El pedido guardado con `clave`, o null si no hay uno válido con productos. */
export function leerPedidoEnCurso(clave: string): PedidoEnCurso | null {
  const s = almacen()
  if (!s) return null
  try {
    const crudo = s.getItem(clave)
    if (!crudo) return null
    const valor: unknown = JSON.parse(crudo)
    if (!esPedido(valor) || valor.items.length === 0) {
      s.removeItem(clave)
      return null
    }
    return { ...valor, idempotencyKey: valor.idempotencyKey ?? null }
  } catch {
    return null
  }
}

export function borrarPedidoEnCurso(clave: string): void {
  try {
    almacen()?.removeItem(clave)
  } catch {
    // nada que hacer
  }
}

/** Unidades vendidas del pedido: suma de cantidades, sin contar los productos
 * que forman parte de un combo (el combo cuenta como una unidad). */
export function unidadesDelPedido(items: ItemTicket[]): number {
  return items.filter((i) => !i.es_hijo_combo).reduce((suma, i) => suma + i.cantidad, 0)
}
