import { describe, expect, it } from 'vitest'
import { fechaEnZona, primerDiaDelMesEnZona, rangoFechasInvertido } from '@/utils/fechaZona'

// 3 oct 2026 a las 19:00 en Ciudad de México (UTC-6) = 4 oct 01:00 UTC.
const NOCHE_MX = new Date('2026-10-04T01:00:00Z')

describe('fechaEnZona', () => {
  it('da la fecha local de la sucursal, no la UTC, después de las 18:00', () => {
    expect(NOCHE_MX.toISOString().slice(0, 10)).toBe('2026-10-04')
    expect(fechaEnZona('America/Mexico_City', NOCHE_MX)).toBe('2026-10-03')
  })

  it('respeta otras zonas', () => {
    expect(fechaEnZona('UTC', NOCHE_MX)).toBe('2026-10-04')
    expect(fechaEnZona('America/Tijuana', new Date('2026-10-04T06:30:00Z'))).toBe('2026-10-03')
  })

  it('con una zona inválida cae a la del navegador sin lanzar error', () => {
    expect(fechaEnZona('Zona/Inexistente', NOCHE_MX)).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})

describe('primerDiaDelMesEnZona', () => {
  it('usa el mes local de la sucursal', () => {
    // 1 nov 2026 00:30 UTC = 31 oct 18:30 en México.
    const momento = new Date('2026-11-01T00:30:00Z')
    expect(primerDiaDelMesEnZona('America/Mexico_City', momento)).toBe('2026-10-01')
    expect(primerDiaDelMesEnZona('UTC', momento)).toBe('2026-11-01')
  })
})

describe('rangoFechasInvertido', () => {
  it('detecta desde posterior a hasta', () => {
    expect(rangoFechasInvertido('2026-10-31', '2026-10-01')).toBe(true)
  })

  it('acepta el mismo día, un rango normal o fechas vacías', () => {
    expect(rangoFechasInvertido('2026-10-01', '2026-10-01')).toBe(false)
    expect(rangoFechasInvertido('2026-10-01', '2026-10-31')).toBe(false)
    expect(rangoFechasInvertido('', '2026-10-01')).toBe(false)
    expect(rangoFechasInvertido('2026-10-01', null)).toBe(false)
  })
})
