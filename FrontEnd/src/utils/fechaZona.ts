/**
 * Fechas de calendario en la zona horaria de la sucursal.
 *
 * `new Date().toISOString()` da la fecha UTC: en México, después de las 18:00
 * ya es "mañana" y los reportes de "hoy" se quedaban sin las ventas del día.
 */

/**
 * Fecha AAAA-MM-DD de `momento` en la zona IANA `zona` (p. ej. la
 * `zona_horaria` de la sucursal). Sin zona, o si la zona no es válida, usa la
 * del navegador.
 */
export function fechaEnZona(zona?: string, momento: Date = new Date()): string {
  let partes: Intl.DateTimeFormatPart[]
  try {
    partes = new Intl.DateTimeFormat('en-US', {
      timeZone: zona || undefined,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    }).formatToParts(momento)
  } catch {
    return fechaEnZona(undefined, momento)
  }
  const valor = (tipo: Intl.DateTimeFormatPartTypes) =>
    partes.find((p) => p.type === tipo)?.value ?? ''
  return `${valor('year')}-${valor('month')}-${valor('day')}`
}

/** Primer día (AAAA-MM-01) del mes en curso de `momento` en la zona `zona`. */
export function primerDiaDelMesEnZona(zona?: string, momento: Date = new Date()): string {
  return `${fechaEnZona(zona, momento).slice(0, 8)}01`
}

/**
 * `true` si `desde` es posterior a `hasta` (fechas AAAA-MM-DD). Con alguna
 * vacía no se considera invertido.
 */
export function rangoFechasInvertido(desde?: string | null, hasta?: string | null): boolean {
  return !!desde && !!hasta && desde > hasta
}
