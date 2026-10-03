import { describe, expect, it } from 'vitest'

import { avisoPulserasBajas, resumenPulseras } from '@/utils/resumenPulseras'
import type { PulseraAdmin } from '@/types/pulsera'

const pulsera = (i: number, activo = true, usada = false): PulseraAdmin => ({
  id: `p${i}`,
  sucursal_id: 's1',
  pulsera_rfid: `WK-${String(i).padStart(7, '0')}`,
  activo,
  usada,
})

// 20 registradas (y una dada de baja): 9 ya se usaron, 4 en estancia, 11 libres.
const INVENTARIO = [
  ...Array.from({ length: 20 }, (_, i) => pulsera(i + 1, true, i < 9)),
  pulsera(99, false),
]

describe('resumen de pulseras de Inicio (UX)', () => {
  it('el total son las registradas y no se encoge al usarlas', () => {
    const r = resumenPulseras(11, { activas: 2, porExpirar: 1, excedidas: 1 }, INVENTARIO)
    expect(r.registradas).toBe(20)
    expect(r.libres).toBe(11)
    // 9 usadas menos las 4 que siguen en estancia = 5 ya consumidas.
    expect(r.usadas).toBe(5)
    expect(r.libres + r.activas + r.porExpirar + r.excedidas + r.usadas).toBe(r.registradas)
  })

  it('sin inventario cae al cálculo anterior y nunca da negativos', () => {
    const r = resumenPulseras(3, { activas: 2, porExpirar: 0, excedidas: 0 }, null)
    expect(r.registradas).toBe(5)
    expect(r.usadas).toBe(0)
    expect(
      resumenPulseras(30, { activas: 0, porExpirar: 0, excedidas: 0 }, INVENTARIO).usadas,
    ).toBe(0)
  })

  it('avisa de existencias bajas', () => {
    expect(avisoPulserasBajas(6, 20)).toBeNull()
    expect(avisoPulserasBajas(5, 20)?.title).toBe('Quedan 5 pulseras libres')
    expect(avisoPulserasBajas(1, 20)?.title).toBe('Queda 1 pulsera libre')
    expect(avisoPulserasBajas(0, 20)?.title).toBe('No quedan pulseras libres')
    expect(avisoPulserasBajas(2, 20)?.detail).toContain('De 20 registradas')
  })
})
