import { describe, expect, it } from 'vitest'
import { nombreArchivoIndicadores } from '@/utils/nombreArchivo'

describe('nombreArchivoIndicadores', () => {
  it('incluye la clave de la sucursal y el periodo', () => {
    expect(nombreArchivoIndicadores('SUC-ZAP-PP', '2026-10-01', '2026-10-03')).toBe(
      'indicadores_SUC-ZAP-PP_2026-10-01_2026-10-03.csv',
    )
  })

  it('sin clave conserva el periodo', () => {
    expect(nombreArchivoIndicadores(null, '2026-10-01', '2026-10-31')).toBe(
      'indicadores_sucursal_2026-10-01_2026-10-31.csv',
    )
    expect(nombreArchivoIndicadores('  ', '2026-10-01', '2026-10-31')).toBe(
      'indicadores_sucursal_2026-10-01_2026-10-31.csv',
    )
  })
})
