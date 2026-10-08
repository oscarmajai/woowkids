import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

/**
 * El administrador de sucursal (sin sucursales:eliminar ni sucursales:editar)
 * no ve "Desactivar sucursal" en su propia sucursal.
 */

const permisos = new Set<string>()

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ hasPermission: (p: string) => permisos.has(p) }),
}))
vi.mock('@/composables/useSucursales', () => ({
  useSucursales: () => ({
    sucursales: ref([
      {
        id: 's1',
        clave: 'SUC-ZAP-PP',
        nombre: 'Zapopan Plaza Patria',
        ciudad: 'Zapopan',
        estado: 'Jalisco',
        gerente: 'Sofía',
        fechaCreacion: '2026-10-01T00:00:00Z',
        statusClave: 'activa',
      },
      {
        id: 's2',
        clave: null,
        nombre: 'Andares',
        ciudad: 'Zapopan',
        estado: 'Jalisco',
        gerente: null,
        fechaCreacion: '2026-01-01T00:00:00Z',
        statusClave: 'inactiva',
      },
    ]),
    loading: ref(false),
    busqueda: ref(''),
    filtros: ref({ estado: null }),
    cargarSucursales: vi.fn(),
    verDetalle: vi.fn(),
  }),
}))

const { default: SucursalesPage } = await import('@/pages/locations/SucursalesPage.vue')

async function montar() {
  const wrapper = mount(SucursalesPage, {
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

describe('SucursalesPage', () => {
  it('sin permisos de editar ni eliminar no ofrece Desactivar ni Reactivar', async () => {
    permisos.add('sucursales:listar')
    const wrapper = await montar()
    expect(wrapper.find('[aria-label="Desactivar"]').exists()).toBe(false)
    expect(wrapper.find('[aria-label="Reactivar"]').exists()).toBe(false)
    expect(wrapper.findAll('[aria-label="Ver detalle"]')).toHaveLength(2)
  })

  it('con los permisos del backend sí los ofrece', async () => {
    permisos.add('sucursales:eliminar')
    permisos.add('sucursales:editar')
    const wrapper = await montar()
    expect(wrapper.find('[aria-label="Desactivar"]').exists()).toBe(true)
    expect(wrapper.find('[aria-label="Reactivar"]').exists()).toBe(true)
  })
})
