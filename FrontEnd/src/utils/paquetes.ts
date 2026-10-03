import type { Paquetes } from '@/types/paquetes'

/**
 * true si el paquete se puede ofrecer para ese tipo de evento (M17). Un
 * paquete sin tipos de evento asignados sirve para todos; sin tipo elegido
 * todavía, tampoco se descarta ninguno.
 */
export function paqueteSirveParaTipo(
  paquete: Pick<Paquetes, 'tipos_evento'>,
  tipoEventoId: string | null | undefined,
): boolean {
  const tipos = paquete.tipos_evento ?? []
  if (!tipoEventoId || tipos.length === 0) return true
  return tipos.some((t) => t.id === tipoEventoId)
}

/** Tipos de evento que hay que asociar y desasociar para pasar de `antes` a `despues`. */
export function diferenciaTipos(
  antes: string[],
  despues: string[],
): { agregar: string[]; quitar: string[] } {
  const previos = new Set(antes)
  const nuevos = new Set(despues)
  return {
    agregar: [...nuevos].filter((id) => !previos.has(id)),
    quitar: [...previos].filter((id) => !nuevos.has(id)),
  }
}
