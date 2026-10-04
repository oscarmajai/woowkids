import { describe, expect, it } from 'vitest'
import { nuevoId } from '@/utils/uuid'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

describe('nuevoId', () => {
  it('usa crypto.randomUUID cuando existe', () => {
    expect(nuevoId()).toMatch(UUID_V4)
  })

  it('por HTTP (sin crypto.randomUUID) genera un UUID v4 válido y distinto', () => {
    const original = crypto.randomUUID
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true })
    try {
      const a = nuevoId()
      const b = nuevoId()
      expect(a).toMatch(UUID_V4)
      expect(b).toMatch(UUID_V4)
      expect(a).not.toBe(b)
    } finally {
      Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true })
    }
  })
})
