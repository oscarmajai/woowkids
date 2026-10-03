import { describe, expect, it } from 'vitest'

import { compraPorRecibir } from '../inventario'

describe('compraPorRecibir (B6)', () => {
  it('cuenta las pendientes y las parciales', () => {
    expect(compraPorRecibir('P')).toBe(true)
    expect(compraPorRecibir('PARCIAL')).toBe(true)
    expect(compraPorRecibir('R')).toBe(false)
    expect(compraPorRecibir('C')).toBe(false)
  })
})
