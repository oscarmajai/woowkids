import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProductosPage from '@/pages/ProductosPage.vue'
import type { ProductoAdmin } from '@/types/producto'

/**
 * M20: el botón Eliminar de productos daba 403 al Administrador, que no tiene
 * `inventario:eliminar_producto`. Ahora solo se muestra a quien lo tiene (el
 * backend exige ese permiso tanto en DELETE como en PATCH activo=false).
 */

const permisos = vi.hoisted(() => ({ codigos: new Set<string>() }))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    currentBranchId: 'suc-1',
    isSistema: false,
    hasPermission: (codigo: string) => permisos.codigos.has(codigo),
  }),
}))
vi.mock('@/api/productosApi', () => ({
  getProductoImagenUrl: () => undefined,
  productosApi: {
    listarAdmin: vi.fn(
      async () =>
        [
          {
            id: 'p-1',
            sucursal_id: 'suc-1',
            nombre: 'Pizza',
            precio_unitario: 95,
            tipo: 'A',
            activo: true,
          },
        ] as unknown as ProductoAdmin[],
    ),
  },
}))

const montar = () =>
  mount(ProductosPage, {
    global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
  })

const eliminar = (wrapper: ReturnType<typeof montar>) =>
  wrapper.findAll('button').filter((b) => b.attributes('aria-label') === 'Eliminar')

describe('ProductosPage (M20)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    permisos.codigos = new Set(['inventario:gestionar_productos'])
  })

  it('sin el permiso de eliminar no ofrece el botón Eliminar', async () => {
    const wrapper = montar()
    await flushPromises()

    expect(wrapper.text()).toContain('Pizza')
    expect(eliminar(wrapper)).toHaveLength(0)
  })

  it('con el permiso de eliminar sí lo ofrece', async () => {
    permisos.codigos.add('inventario:eliminar_producto')
    const wrapper = montar()
    await flushPromises()

    expect(eliminar(wrapper)).toHaveLength(1)
  })
})
