import type { Reservaciones } from '@/types/reservaciones'

/** Días antes del evento en que debe quedar liquidado. Después ya no se edita. */
export const DIAS_LIMITE_LIQUIDACION = 7

/**
 * Fecha límite para liquidar (y para modificar) una reservación: una semana
 * antes del evento. Pasado ese punto la reservación se cancela sola si sigue
 * debiendo, así que tampoco tiene sentido seguir cambiándole el alcance.
 */
export function fechaLimiteLiquidacion(fechaEvento: string): Date {
  const limite = new Date(`${fechaEvento}T00:00:00`)
  limite.setDate(limite.getDate() - DIAS_LIMITE_LIQUIDACION)
  return limite
}

/** true si la reservación todavía está dentro del plazo para modificarse. */
export function dentroDePlazo(fechaEvento: string, hoy = new Date()): boolean {
  const inicioDeHoy = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate())
  return inicioDeHoy < fechaLimiteLiquidacion(fechaEvento)
}

const num = (v: string | number): number => (typeof v === 'number' ? v : parseFloat(v) || 0)

/** Piso de anticipo del negocio; un paquete puede pedir más (`anticipo_porcentaje`). */
export const PORCENTAJE_ANTICIPO_MINIMO = 30

/**
 * Porcentaje mínimo de anticipo de un paquete: el 30 % del negocio o el del
 * paquete si es mayor (M16). Misma regla que valida el servidor.
 */
export function porcentajeAnticipoMinimo(
  anticipoPorcentajePaquete?: string | number | null,
): number {
  const pct = Number(anticipoPorcentajePaquete ?? NaN)
  return Number.isFinite(pct)
    ? Math.max(PORCENTAJE_ANTICIPO_MINIMO, pct)
    : PORCENTAJE_ANTICIPO_MINIMO
}

/**
 * Monto de un porcentaje del total, redondeado a pesos completos (mitades hacia
 * arriba), igual que el servidor. Se calcula en centavos enteros para que un
 * caso como 30 % de $7,615 (= $2,284.50) no caiga en $2,284.4999… por el
 * redondeo binario y dé un mínimo distinto al del backend.
 */
export function montoPorPorcentaje(total: number, porcentaje: number): number {
  const centavos = Math.round(total * 100)
  return Math.round((centavos * porcentaje) / 10000)
}

/** Días completos de hoy (fecha local) a la fecha del evento ('YYYY-MM-DD'). */
export function diasParaEvento(fechaEvento: string, hoy = new Date()): number {
  const [y, m, d] = fechaEvento.slice(0, 10).split('-').map(Number)
  const evento = Date.UTC(y!, m! - 1, d!)
  const inicioDeHoy = Date.UTC(hoy.getFullYear(), hoy.getMonth(), hoy.getDate())
  return Math.round((evento - inicioDeHoy) / 86_400_000)
}

/**
 * A 7 días o menos del evento ya no hay plazo para "liquidar después": se cobra
 * el 100 % al reservar. Si no, la reservación se cancelaría sola por falta de
 * pago en menos de una hora (C3). El servidor aplica la misma regla.
 */
export function exigeLiquidacionAlReservar(dias: number): boolean {
  return dias <= DIAS_LIMITE_LIQUIDACION
}

/**
 * Recalcula el total de una reservación a partir de sus partes.
 *
 * Se reconstruye desde los componentes en vez de sumar o restar diferencias
 * sobre el total anterior: así una edición no arrastra errores de redondeo de
 * las anteriores, y el total siempre corresponde a lo que muestra el desglose.
 *
 * `precio_horas` se conserva tal cual porque es histórico: pertenece a
 * reservaciones levantadas cuando el paquete cobraba una tarifa por hora de
 * salón (antes de la migración 034). Las nuevas lo traen en cero.
 */
export function calcularTotal(partes: {
  precio_base: string | number
  precio_pulseras: string | number
  precio_horas: string | number
  precio_productos: string | number
  precio_extras: string | number
  descuento: string | number
}): number {
  return (
    num(partes.precio_base) +
    num(partes.precio_pulseras) +
    num(partes.precio_horas) +
    num(partes.precio_productos) +
    num(partes.precio_extras) -
    num(partes.descuento)
  )
}

/** Cargo de pulseras: tarifa por hora × invitados × horas del evento. */
export function calcularPulseras(
  precioHoraPulsera: string | number,
  invitados: number,
  horas: number,
): number {
  return num(precioHoraPulsera) * invitados * Math.max(1, horas)
}

/**
 * Desglose del cargo de pulseras guardado en `precio_personas_extra` (B19):
 * "12 × 3 h a $70.00". La columna conserva su nombre por compatibilidad, pero
 * desde la migración 034 es tarifa por hora × invitados × horas, no un cargo
 * por "personas extra". La tarifa se deduce del importe para no depender de la
 * tarifa vigente del paquete, que pudo cambiar después de reservar.
 */
export function detallePulseras(
  reservacion: Pick<
    Reservaciones,
    'numero_personas' | 'horas_reservadas' | 'precio_personas_extra'
  >,
  horasDelHorario: number,
): { invitados: number; horas: number; tarifa: number } {
  const invitados = reservacion.numero_personas
  const horas = Math.max(1, reservacion.horas_reservadas || horasDelHorario)
  const tarifa = invitados > 0 ? num(reservacion.precio_personas_extra) / (invitados * horas) : 0
  return { invitados, horas, tarifa: Math.round(tarifa * 100) / 100 }
}

export type UnidadExtra = 'evento' | 'persona' | 'hora'

/**
 * Veces que se cobra un extra según su unidad (M15): "persona" una por
 * invitado, "hora" una por hora del evento (mínimo 1) y "evento" (o una unidad
 * desconocida) se conserva `actual`, que en el alta es 1. Misma regla que el
 * servidor (`cantidad_extra` en `reservacion_precio.py`).
 */
export function cantidadExtra(
  unidad: string | null | undefined,
  invitados: number,
  horas: number,
  actual = 1,
): number {
  if (unidad === 'persona') return Math.max(1, invitados)
  if (unidad === 'hora') return Math.max(1, horas)
  return Math.max(1, actual)
}

/** Texto corto de la unidad de un extra, para mostrar junto a su precio. */
export function etiquetaUnidadExtra(unidad: string | null | undefined): string {
  if (unidad === 'persona') return 'por persona'
  if (unidad === 'hora') return 'por hora'
  return 'por evento'
}

/** Un extra ya guardado en la reservación, con la unidad de su catálogo. */
export interface ExtraCobrado {
  unidad: string | null | undefined
  precio_unitario: string | number
  cantidad: number
}

/** Total de los extras con la cantidad que les toca a esos invitados y horas. */
export function totalExtras(extras: ExtraCobrado[], invitados: number, horas: number): number {
  return extras.reduce(
    (suma, e) =>
      suma + num(e.precio_unitario) * cantidadExtra(e.unidad, invitados, horas, e.cantidad),
    0,
  )
}

export interface CambioReservacion {
  numero_personas: number
  horas_reservadas: number
  precio_personas_extra: string
  precio_extras: string
  precio_total: string
}

/**
 * Calcula cómo queda una reservación al cambiarle invitados y/u horas. Replica
 * el cálculo del servidor (`app/services/reservacion_precio.py`), que es el que
 * manda: si no coincide, el PATCH responde 409 con el precio real.
 *
 * `extras`: los extras guardados de la reservación con su unidad. Los que se
 * cobran por persona o por hora cambian con invitados u horas (M15), igual que
 * en el servidor. Si no se pasan (o no hay), se conserva `precio_extras`.
 *
 * Devuelve también `anticipoExcede`: si el total nuevo queda por debajo de lo
 * ya pagado (`monto_pagado`, todos los pagos menos el cambio), el servidor
 * rechaza la edición. Quien llame debe impedir el guardado en ese caso.
 */
export function recalcularReservacion(
  reservacion: Reservaciones,
  precioHoraPulsera: string | number,
  cambios: { invitados?: number; horas?: number },
  extras: ExtraCobrado[] = [],
): CambioReservacion & { anticipoExcede: boolean; totalAnterior: number } {
  const invitados = cambios.invitados ?? reservacion.numero_personas
  const horas = Math.max(1, cambios.horas ?? reservacion.horas_reservadas)

  const pulseras = calcularPulseras(precioHoraPulsera, invitados, horas)
  const precioExtras = extras.length
    ? totalExtras(extras, invitados, horas)
    : num(reservacion.precio_extras)
  const total = calcularTotal({
    precio_base: reservacion.precio_base,
    precio_pulseras: pulseras,
    precio_horas: reservacion.precio_horas,
    precio_productos: reservacion.precio_productos,
    precio_extras: precioExtras,
    descuento: reservacion.descuento,
  })

  return {
    numero_personas: invitados,
    horas_reservadas: horas,
    precio_personas_extra: String(pulseras),
    precio_extras: String(precioExtras),
    precio_total: String(total),
    anticipoExcede: total < num(reservacion.monto_pagado),
    totalAnterior: num(reservacion.precio_total),
  }
}

/**
 * Suma horas a la hora de fin. Devuelve "HH:mm:ss".
 *
 * Se topa en 23:59:59 en vez de pasar al día siguiente: la reservación guarda
 * una sola fecha y un horario que debe cumplir `hora_fin > hora_inicio`, así
 * que cruzar la medianoche rompería esa restricción.
 */
export function sumarHoras(horaFin: string, horas: number): string {
  const [h = 0, m = 0] = horaFin.split(':').map(Number)
  const minutosTotales = Math.min(h * 60 + m + horas * 60, 23 * 60 + 59)
  const hh = String(Math.floor(minutosTotales / 60)).padStart(2, '0')
  const mm = String(minutosTotales % 60).padStart(2, '0')
  return `${hh}:${mm}:00`
}
