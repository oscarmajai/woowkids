import { describe, expect, it } from 'vitest'
import {
  esCuentaProtegida,
  nombresSucursales,
  perteneceASucursal,
  sucursalesDe,
} from '@/utils/usuarios'

const SUCURSALES = [
  { id: 's1', nombre: 'Andares' },
  { id: 's2', nombre: 'Zapopan Plaza Patria' },
]

describe('esCuentaProtegida', () => {
  it('protege la cuenta de sistema y a cualquier AdministradorSistema', () => {
    expect(esCuentaProtegida({ id: 'sys', role: 'AdministradorSistema' }, 'yo')).toBe(true)
  })

  it('protege la propia cuenta, sea cual sea el rol', () => {
    expect(esCuentaProtegida({ id: 'yo', role: 'Administrador' }, 'yo')).toBe(true)
  })

  it('no protege a los demás usuarios', () => {
    expect(esCuentaProtegida({ id: 'u1', role: 'Cajero' }, 'yo')).toBe(false)
    expect(esCuentaProtegida({ id: 'u1', role: 'Administrador' }, null)).toBe(false)
  })
})

describe('sucursales de un usuario', () => {
  it('un Administrador sin sucursal fija sale con las suyas', () => {
    const admin = { branchId: null, branchIds: ['s2'] }
    expect(sucursalesDe(admin)).toEqual(['s2'])
    expect(perteneceASucursal(admin, 's2')).toBe(true)
    expect(nombresSucursales(admin, SUCURSALES)).toBe('Zapopan Plaza Patria')
  })

  it('un Administrador con varias sucursales las lista todas', () => {
    const admin = { branchId: null, branchIds: ['s1', 's2'] }
    expect(nombresSucursales(admin, SUCURSALES)).toBe('Andares, Zapopan Plaza Patria')
  })

  it('un rol con sucursal fija sigue usando branchId si no llegan las demás', () => {
    const cajero = { branchId: 's1', branchIds: [] }
    expect(sucursalesDe(cajero)).toEqual(['s1'])
    expect(perteneceASucursal(cajero, 's2')).toBe(false)
  })

  it('sin sucursal muestra un guion', () => {
    expect(nombresSucursales({ branchId: null, branchIds: [] }, SUCURSALES)).toBe('—')
  })
})
