/**
 * M26: notas y alergias del niño (campo "Notas / Alergias" del registro).
 * Es texto libre, así que cualquier nota capturada se trata como algo que
 * quien cuida al niño tiene que ver: en la tarjeta de Control de Acceso, en
 * "Requiere atención" de Inicio y en el comprobante.
 */

/** Texto de la nota listo para mostrarse, o null si no hay nota. */
export function notaVisible(notas: string | null | undefined): string | null {
  const texto = notas?.trim()
  return texto ? texto : null
}

export interface NinoConNotas {
  detalleId: string
  nino: string
  pulsera: string
  notas: string | null
}

export interface AvisoNotas {
  key: string
  title: string
  detail: string
}

/** Un aviso de "Requiere atención" por cada niño en estancia con notas. */
export function avisosDeNotas(ninos: NinoConNotas[]): AvisoNotas[] {
  return ninos.flatMap((n) => {
    const nota = notaVisible(n.notas)
    if (!nota) return []
    return [
      {
        key: `notas-${n.detalleId}`,
        title: `${n.nino}: notas / alergias`,
        detail: `${nota} · Pulsera ${n.pulsera}`,
      },
    ]
  })
}
