import { describe, expect, it } from 'vitest'

import { ordenCancelada } from './estadoOrden'

describe('ordenCancelada', () => {
  it('una comanda en C está cancelada', () => {
    expect(ordenCancelada('comanda', 'C')).toBe(true)
    expect(ordenCancelada('comanda', 'E')).toBe(false)
  })

  it('una estancia cerrada (C) NO está cancelada: el niño solo ya salió', () => {
    expect(ordenCancelada('estancia', 'C')).toBe(false)
    expect(ordenCancelada('estancia', 'A')).toBe(false)
  })

  it('una reservación se cancela con "cancelada"', () => {
    expect(ordenCancelada('reservacion', 'cancelada')).toBe(true)
    expect(ordenCancelada('reservacion', 'confirmada')).toBe(false)
    expect(ordenCancelada('reservacion', 'C')).toBe(false)
  })

  it('sin estado no hay cancelación', () => {
    expect(ordenCancelada('comanda', null)).toBe(false)
    expect(ordenCancelada(undefined, undefined)).toBe(false)
  })
})
