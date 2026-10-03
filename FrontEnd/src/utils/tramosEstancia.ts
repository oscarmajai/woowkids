import type { TramoEstancia } from '@/types/producto'

/**
 * Tramos de precio de la estancia (`config_estancia` del producto tipo 'E').
 *
 * Los rangos se comparan como semiabiertos: "0–1 h" y "1–2 h" comparten el
 * extremo 1 pero NO se solapan (antes se rechazaban). Para cotizar, los tramos
 * se recorren ordenados por `min_horas` y gana el primero que cubre las horas
 * (inclusivo), así que en el extremo compartido gana el tramo que termina ahí:
 * 1 h → "0–1 h", 2 h → "1–2 h". Los tramos sin extremos compartidos ("1–1",
 * "2–3") se cotizan igual que antes. El backend aplica la misma regla
 * (`app/services/tramos_estancia.py::precio_por_hora`).
 */

function ordenados(tramos: TramoEstancia[]): TramoEstancia[] {
  return [...tramos].sort((a, b) => a.min_horas - b.min_horas || a.max_horas - b.max_horas)
}

/**
 * ¿Dos tramos cubren las mismas horas? Un tramo de un solo punto ("1–1") choca
 * con otro que contenga ese punto (incluidos sus extremos), porque uno de los
 * dos nunca se usaría.
 */
export function seSolapan(a: TramoEstancia, b: TramoEstancia): boolean {
  const aPunto = a.min_horas === a.max_horas
  const bPunto = b.min_horas === b.max_horas
  if (aPunto && bPunto) return a.min_horas === b.min_horas
  if (aPunto) return b.min_horas <= a.min_horas && a.min_horas <= b.max_horas
  if (bPunto) return a.min_horas <= b.min_horas && b.min_horas <= a.max_horas
  return Math.max(a.min_horas, b.min_horas) < Math.min(a.max_horas, b.max_horas)
}

/** Motivo por el que no se puede agregar el tramo, o null si es válido. */
export function validarTramoNuevo(
  tramo: TramoEstancia,
  existentes: TramoEstancia[],
): string | null {
  const { min_horas, max_horas, precio } = tramo
  if (!(min_horas >= 0) || !(max_horas >= 0) || !(precio > 0)) {
    return 'Las horas deben ser 0 o más y el precio por hora mayor a 0.'
  }
  if (min_horas > max_horas) return 'El mínimo de horas no puede ser mayor al máximo.'
  const choque = existentes.find((t) => seSolapan(t, tramo))
  if (choque) {
    return (
      `El rango ${min_horas}–${max_horas} h se solapa con el de ` +
      `${choque.min_horas}–${choque.max_horas} h.`
    )
  }
  return null
}

/** Tramo que se cobra por `horas`; si ninguno las cubre, el de menor `min_horas`. */
export function tramoParaHoras(tramos: TramoEstancia[], horas: number): TramoEstancia | null {
  if (!tramos.length) return null
  const lista = ordenados(tramos)
  return lista.find((t) => horas >= t.min_horas && horas <= t.max_horas) ?? lista[0]
}
