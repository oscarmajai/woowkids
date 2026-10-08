import type { DetalleProducto } from '@/api/historialApi'

/** Un renglón de la orden: un producto suelto o un combo con sus productos. */
export interface RenglonOrden {
  renglon: DetalleProducto
  hijos: DetalleProducto[]
}

/**
 * Agrupa los detalles de una orden por renglón: cada producto de combo
 * va bajo el renglón del combo al que pertenece, no bajo todos los combos con
 * el mismo nombre.
 *
 * - Con `detalle_padre_id` (órdenes nuevas) el enlace es exacto.
 * - Órdenes viejas sin ese dato: las unidades (`id_combo_padre`) se reparten
 *   entre los renglones del combo en orden, según su cantidad; un hijo sin
 *   unidad va al primer renglón de su combo. Si no hay ningún renglón con ese
 *   nombre, el hijo se muestra como renglón propio.
 */
export function agruparPorRenglon(detalles: DetalleProducto[]): RenglonOrden[] {
  const principales = detalles.filter((d) => !d.nombre_combo_padre)
  const resultado: RenglonOrden[] = principales.map((renglon) => ({ renglon, hijos: [] }))
  const porId = new Map(resultado.map((r) => [r.renglon.id, r]))

  const sinEnlace: DetalleProducto[] = []
  for (const d of detalles) {
    if (!d.nombre_combo_padre) continue
    const padre = d.detalle_padre_id ? porId.get(d.detalle_padre_id) : undefined
    if (padre) padre.hijos.push(d)
    else sinEnlace.push(d)
  }

  const porCombo = new Map<string, DetalleProducto[]>()
  for (const h of sinEnlace) {
    const nombre = h.nombre_combo_padre as string
    porCombo.set(nombre, [...(porCombo.get(nombre) ?? []), h])
  }

  for (const [nombre, hijos] of porCombo) {
    const padres = resultado.filter(
      (r) => r.renglon.producto_nombre === nombre && !r.renglon.nombre_combo_padre,
    )
    if (padres.length === 0) {
      for (const h of hijos) resultado.push({ renglon: h, hijos: [] })
      continue
    }
    // Unidades en el orden en que aparecen; cada renglón toma `cantidad`.
    const unidades = new Map<string, DetalleProducto[]>()
    for (const h of hijos) {
      if (!h.id_combo_padre) {
        padres[0]!.hijos.push(h)
        continue
      }
      unidades.set(h.id_combo_padre, [...(unidades.get(h.id_combo_padre) ?? []), h])
    }
    let cursor = 0
    const cupos = padres.flatMap((p) =>
      Array<RenglonOrden>(Math.max(p.renglon.cantidad, 1)).fill(p),
    )
    for (const grupo of unidades.values()) {
      const destino = cupos[Math.min(cursor, cupos.length - 1)]!
      destino.hijos.push(...grupo)
      cursor += 1
    }
  }

  return resultado
}

/**
 * Productos de un combo para el ticket: suma los iguales (mismo producto y
 * misma nota), así un 2x combo dice "2x Hot dog" en vez de repetirlo.
 */
export function resumirHijos(hijos: DetalleProducto[]): DetalleProducto[] {
  const resumen = new Map<string, DetalleProducto>()
  for (const h of hijos) {
    const clave = `${h.producto_nombre}\u0000${h.notas_especiales ?? ''}`
    const previo = resumen.get(clave)
    if (previo) resumen.set(clave, { ...previo, cantidad: previo.cantidad + h.cantidad })
    else resumen.set(clave, { ...h })
  }
  return [...resumen.values()]
}
