import { describe, expect, it } from 'vitest'

import { agruparCanjes } from '@/utils/kardexLealtad'
import type { MovimientoPuntos, TipoMovimientoPuntos } from '@/types/lealtad'

let n = 0
const mov = (
  tipo: TipoMovimientoPuntos,
  puntos: number,
  saldo: number,
  creado: string,
  extra: Partial<MovimientoPuntos> = {},
): MovimientoPuntos => ({
  id: `m${++n}`,
  sucursal_id: 's1',
  celular: '3312345678',
  lote_id: `l${n}`,
  comanda_id: 'c1',
  tipo,
  puntos,
  saldo_resultante: saldo,
  notas: null,
  creado,
  creado_por: null,
  ...extra,
})

const T_CANJE = '2026-10-03T19:10:00.123456+00:00'

describe('kardex de lealtad: un renglón por canje (UX)', () => {
  it('junta los lotes de un mismo canje sin perder los demás movimientos', () => {
    // Como lo devuelve el backend (creado DESC): canje de 50 pts en 3 lotes.
    const movimientos = [
      mov('R', -9, 47, T_CANJE),
      mov('R', -8, 39, T_CANJE),
      mov('R', -33, 6, T_CANJE),
      mov('O', 20, 56, '2026-10-03T18:00:00+00:00', { comanda_id: 'c0' }),
    ]

    const vista = agruparCanjes(movimientos)

    expect(vista).toHaveLength(2)
    expect(vista[0]).toMatchObject({ tipo: 'R', puntos: -50, saldo_resultante: 6, lotes: 3 })
    expect(vista[1]).toMatchObject({ tipo: 'O', puntos: 20, lotes: 1 })
    // La suma de puntos no cambia (los KPIs siguen cuadrando).
    const suma = (l: { puntos: number }[]) => l.reduce((s, m) => s + m.puntos, 0)
    expect(suma(vista)).toBe(suma(movimientos))
    // No toca los movimientos originales.
    expect(movimientos[0].puntos).toBe(-9)
  })

  it('dos canjes distintos siguen siendo dos renglones', () => {
    const vista = agruparCanjes([
      mov('R', -10, 40, T_CANJE),
      mov('R', -5, 35, '2026-10-03T19:30:00+00:00'),
      mov('R', -7, 33, T_CANJE, { comanda_id: 'c2' }),
    ])
    expect(vista.map((m) => m.puntos)).toEqual([-10, -5, -7])
  })
})
