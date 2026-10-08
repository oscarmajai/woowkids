import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { UserListItem } from '@/types/user'

/**
 * El formulario no tiene selector de sucursal para el rol Administrador (se
 * asigna desde la sucursal) y debe indicarlo. Tampoco debe ofrecer "Eliminar
 * usuario" en la propia cuenta.
 */

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

const USUARIOS: Record<string, UserListItem> = {
  adm: usuario({ id: 'adm', name: 'Sofía', role: 'Administrador', branchIds: ['s2'] }),
  yo: usuario({ id: 'yo', name: 'Luis', role: 'Administrador', branchIds: ['s1'] }),
}

vi.mock('@/services/userService', () => ({
  userService: { getUser: vi.fn(async (id: string) => USUARIOS[id]) },
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    currentUser: { id: 'yo' },
    hasRole: (r: string) => r === 'AdministradorSistema',
    hasPermission: () => true,
  }),
}))
vi.mock('@/stores/roles', () => ({
  useRolesStore: () => ({
    roles: [
      { nombre: 'Administrador', activo: true, requiere_sucursal: false },
      { nombre: 'Cajero', activo: true, requiere_sucursal: true },
    ],
    cargar: vi.fn(),
  }),
}))

const { default: UserFormDialog } = await import('@/components/usuarios/UserFormDialog.vue')

const SUCURSALES = [
  { id: 's1', nombre: 'Andares', isActive: true },
  { id: 's2', nombre: 'Zapopan Plaza Patria', isActive: true },
]

async function montar(userId: string) {
  const wrapper = mount(UserFormDialog, {
    attachTo: document.body,
    props: { modelValue: true, userId, branches: SUCURSALES as never },
  })
  await flushPromises()
  return wrapper
}

describe('UserFormDialog', () => {
  it('con rol Administrador explica dónde se asigna la sucursal y cuáles tiene', async () => {
    const wrapper = await montar('adm')
    const texto = document.body.textContent ?? ''
    expect(texto).toContain('Sucursales → Editar sucursal → Administrador')
    expect(texto).toContain('Administra: Zapopan Plaza Patria')
    expect(texto).toContain('Eliminar usuario')
    wrapper.unmount()
  })

  it('en la propia cuenta no ofrece "Eliminar usuario"', async () => {
    const wrapper = await montar('yo')
    expect(document.body.textContent ?? '').not.toContain('Eliminar usuario')
    wrapper.unmount()
  })
})
