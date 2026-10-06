import type { PulseraAdmin } from '@/types/pulsera'

/**
 * Pulseras de la sucursal para la tarjeta de Inicio.
 *
 * Las pulseras son de un solo uso (`repositories/pulseras.py`): una vez
 * asignada a un niño ya no vuelve a estar libre. Antes la tarjeta decía
 * "N libres de M" con M = libres + en estancia, así que M se encogía con cada
 * salida sin explicar por qué. Ahora el total son las pulseras registradas
 * (activas) y se muestran aparte las que ya se usaron.
 */

/** Con esta cantidad de pulseras libres o menos se avisa en "Requiere atención". */
export const UMBRAL_PULSERAS_BAJAS = 5

export interface EnEstancia {
  activas: number
  porExpirar: number
  excedidas: number
}

export interface ResumenPulseras extends EnEstancia {
  libres: number
  /** Ya se usaron y no se pueden volver a asignar (sin contar las en estancia). */
  usadas: number
  /** Pulseras activas registradas en la sucursal. */
  registradas: number
}

/**
 * `inventario` es el listado de pulseras de la sucursal (null si no se pudo
 * cargar: entonces el total cae a libres + en estancia, como antes).
 */
export function resumenPulseras(
  libres: number,
  enEstancia: EnEstancia,
  inventario: PulseraAdmin[] | null,
): ResumenPulseras {
  const enUso = enEstancia.activas + enEstancia.porExpirar + enEstancia.excedidas
  const registradas = inventario ? inventario.filter((p) => p.activo).length : libres + enUso
  return {
    ...enEstancia,
    libres,
    registradas,
    // Las libres y las en estancia vienen en vivo; el inventario se carga una
    // vez: nunca se muestra un negativo si cambió entre una lectura y otra.
    usadas: Math.max(0, registradas - libres - enUso),
  }
}

export interface AvisoPulseras {
  title: string
  detail: string
}

/** Aviso de existencias bajas para "Requiere atención", o null si alcanzan. */
export function avisoPulserasBajas(libres: number, registradas: number): AvisoPulseras | null {
  if (libres > UMBRAL_PULSERAS_BAJAS) return null
  return {
    title:
      libres === 0
        ? 'No quedan pulseras libres'
        : libres === 1
          ? 'Queda 1 pulsera libre'
          : `Quedan ${libres} pulseras libres`,
    detail: `De ${registradas} registradas. Son de un solo uso: registra pulseras nuevas.`,
  }
}
