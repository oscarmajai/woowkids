import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import type { UserListItem } from '@/types/user'

/**
 * Administración de usuarios: el sysadmin no ve Editar/Eliminar en la cuenta
 * de sistema ni en la suya, los administradores muestran su sucursal y el
 * diálogo de Eliminar no dice "no se puede deshacer", porque el usuario
 * queda inactivo y se puede reactivar.
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

const USUARIOS: UserListItem[] = [
  usuario({
    id: 'sys',
    name: 'Sistema',
    role: 'AdministradorSistema',
    email: 'sistema@mercury.internal',
  }),
  usuario({ id: 'yo', name: 'Yo Sysadmin', role: 'AdministradorSistema' }),
  usuario({ id: 'adm', name: 'Sofía Admin', role: 'Administrador', branchIds: ['s2'] }),
  usuario({ id: 'caj', name: 'Diego Cajero', role: 'Cajero', branchId: 's2', branchIds: ['s2'] }),
]

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: vi.fn() }),
}))
vi.mock('@/services/userService', () => ({
  userService: {
    listUsers: vi.fn(async () => USUARIOS),
    deleteUser: vi.fn(),
  },
}))
vi.mock('@/services/branchService', () => ({
  branchService: {
    listBranches: vi.fn(async () => [
      { id: 's1', nombre: 'Andares', isActive: true },
      { id: 's2', nombre: 'Zapopan Plaza Patria', isActive: true },
    ]),
  },
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    currentUser: { id: 'yo' },
    hasPermission: () => true,
    hasRole: (r: string) => r === 'AdministradorSistema',
  }),
}))
vi.mock('@/stores/roles', () => ({ useRolesStore: () => ({ roles: [{}], cargar: vi.fn() }) }))

const { default: UsersPage } = await import('@/pages/sysadmin/UsersPage.vue')

async function montar() {
  const wrapper = mount(UsersPage, {
    attachTo: document.body,
    global: {
      stubs: { QPage: { template: '<div><slot /></div>' }, UserFormDialog: true },
    },
  })
  await flushPromises()
  return wrapper
}

function fila(wrapper: Awaited<ReturnType<typeof montar>>, nombre: string) {
  const tr = wrapper.findAll('tbody tr').find((r) => r.text().includes(nombre))
  if (!tr) throw new Error(`No se encontró la fila de ${nombre}`)
  return tr
}

describe('UsersPage', () => {
  it('no ofrece Editar ni Eliminar en la cuenta de sistema ni en la propia', async () => {
    const wrapper = await montar()

    for (const nombre of ['Sistema', 'Yo Sysadmin']) {
      const tr = fila(wrapper, nombre)
      expect(tr.find('[aria-label="Editar"]').exists()).toBe(false)
      expect(tr.find('[aria-label="Eliminar"]').exists()).toBe(false)
    }
    const otro = fila(wrapper, 'Diego Cajero')
    expect(otro.find('[aria-label="Editar"]').exists()).toBe(true)
    expect(otro.find('[aria-label="Eliminar"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('el administrador sale con su sucursal', async () => {
    const wrapper = await montar()
    expect(fila(wrapper, 'Sofía Admin').text()).toContain('Zapopan Plaza Patria')
    wrapper.unmount()
  })

  it('el diálogo de Eliminar dice que el usuario queda inactivo y se puede reactivar', async () => {
    const wrapper = await montar()
    await fila(wrapper, 'Diego Cajero').find('[aria-label="Eliminar"]').trigger('click')
    await flushPromises()

    const texto = document.body.textContent ?? ''
    expect(texto).toContain('queda inactivo')
    expect(texto).toContain('reactivarlo')
    expect(texto).not.toContain('no se puede deshacer')
    wrapper.unmount()
  })
})
