import { describe, expect, it } from 'vitest'
import { reglaClaveSucursal } from '@/utils/validators'

describe('reglaClaveSucursal', () => {
  it('al crear, la clave es obligatoria', () => {
    const regla = reglaClaveSucursal(false)
    expect(regla('')).toBe('La clave es requerida')
    expect(regla('   ')).toBe('La clave es requerida')
    expect(regla(null)).toBe('La clave es requerida')
    expect(regla('SUC-ZAP-PP')).toBe(true)
  })

  it('al editar, una sucursal sin clave se puede guardar', () => {
    const regla = reglaClaveSucursal(true)
    expect(regla('')).toBe(true)
    expect(regla(null)).toBe(true)
  })
})
