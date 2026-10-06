import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Branch } from '@/types/branch'
import type { UserListItem } from '@/types/user'

/**
 * Detalle de la sucursal: el administrador cuenta entre sus usuarios, el KPI
 * "Administrador" muestra su correo (no el de la sucursal) y "Desactivar"
 * solo se ofrece con sucursales:eliminar.
 */

const permisos = new Set<string>()

const SUCURSAL = {
  id: 's1',
  nombre: 'Zapopan Plaza Patria',
  direccion: null,
  ciudad: null,
  estado: null,
  codigoPostal: null,
  zonaHoraria: 'America/Mexico_City',
  horaApertura: '10:00:00',
  horaCierre: '21:00:00',
  telefono: null,
  correo: 'plazapatria@woowkids.mx',
  clave: 'SUC-ZAP-PP',
  administradorId: 'adm',
  administradorName: 'Sofía Admin',
  administradorEmail: 'admin.zapopan@woowkids.mx',
  isActive: true,
  creado: null,
  creadoPor: null,
  creadorName: null,
  modificado: null,
  modificadoPor: null,
  modificadorName: null,
} satisfies Branch

const usuario = (over: Partial<UserListItem>): UserListItem => ({
  id: 'u',
  name: 'Usuario',
  lastName: null,
  phone: null,
  email: 'u@test.local',
  role: 'Cajero',
  branchId: null,
  branchIds: [],
  isActive: true,
  lastAccess: null,
  tienePin: false,
  ...over,
})

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 's1' } }),
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: (p: string) => permisos.has(p) }),
}))
vi.mock('@/services/branchService', () => ({
  branchService: {
    getBranch: vi.fn(async () => SUCURSAL),
    getIndicadores: vi.fn(async () => ({
      ventas: 0,
      ninosAtendidos: 0,
      eventos: 0,
      cajasAbiertas: 0,
    })),
    exportarIndicadores: vi.fn(),
  },
}))
vi.mock('@/services/userService', () => ({
  userService: {
    listUsers: vi.fn(async () => [
      usuario({ id: 'adm', name: 'Sofía Admin', role: 'Administrador', branchIds: ['s1'] }),
      usuario({ id: 'caj', name: 'Diego Cajero', branchId: 's1', branchIds: ['s1'] }),
      usuario({ id: 'otro', name: 'De Andares', branchId: 's2', branchIds: ['s2'] }),
    ]),
  },
}))
vi.mock('@/services/cajaAdminService', () => ({ cajaAdminService: { listCajas: vi.fn() } }))
vi.mock('@/services/horarioService', () => ({ horarioService: { listHorarios: vi.fn() } }))

const { default: DetailBranchPage } = await import('@/components/DetailBranchPage.vue')

async function montar() {
  const wrapper = mount(DetailBranchPage, {
    global: {
      stubs: {
        QPage: { template: '<div><slot /></div>' },
        SucursalFormDialog: true,
        SucursalModalDesactivar: true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => permisos.clear())

describe('DetailBranchPage', () => {
  it('cuenta al administrador entre los usuarios y muestra su correo, no el de la sucursal', async () => {
    const wrapper = await montar()
    const texto = wrapper.text()

    expect(texto).toContain('Sofía Admin')
    expect(texto).toContain('Diego Cajero')
    expect(texto).not.toContain('De Andares')
    expect(texto).toContain('2 usuarios')
    expect(texto).toContain('admin.zapopan@woowkids.mx')
    expect(texto).not.toContain('plazapatria@woowkids.mx')
  })

  it('sin sucursales:eliminar no ofrece Desactivar', async () => {
    permisos.add('sucursales:ver')
    const wrapper = await montar()
    expect(wrapper.findAll('button').some((b) => b.text().includes('Desactivar'))).toBe(false)
  })

  it('con sucursales:eliminar sí lo ofrece', async () => {
    permisos.add('sucursales:eliminar')
    const wrapper = await montar()
    expect(wrapper.findAll('button').some((b) => b.text().includes('Desactivar'))).toBe(true)
  })
})
