import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import CajaComponent from '../CajaComponent.vue'
import ProductoCard from '@/components/comandas/ProductoCard.vue'
import TicketPanel from '@/components/comandas/TicketPanel.vue'
import PaymentModal from '@/components/shared/payments/PaymentModal.vue'
import { pagosApi } from '@/api/pagosApi'
import { obtenerProductos } from '@/services/productoService'
import type { Producto } from '@/types/producto'

const notify = vi.fn()

vi.mock('quasar', async (original) => ({
  ...(await original<typeof import('quasar')>()),
  useQuasar: () => ({ notify }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/api/pagosApi', () => ({ pagosApi: { completarPago: vi.fn() } }))
vi.mock('@/api/metodosPagoApi', () => ({
  metodosPagoApi: {
    listar: vi.fn().mockResolvedValue([
      {
        id: 'efectivo',
        nombre: 'Efectivo',
        descripcion: null,
        tipo: 'E',
        comision_porcentaje: null,
        requiere_referencia: false,
        activo: true,
      },
    ]),
  },
}))
vi.mock('@/services/productoService', () => ({
  obtenerProductos: vi.fn(),
  obtenerComboHijos: vi.fn(),
}))
vi.mock('@/composables/useComandasSocket', () => ({ useComandasSocket: vi.fn() }))
vi.mock('@/composables/useCajaMetrics', () => ({
  useCajaMetrics: () => ({
    comandasActivas: ref([]),
    productos: ref([]),
    refrescarComandas: vi.fn(),
  }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ currentBranchId: 's1' }) }))
vi.mock('@/stores/turnoCaja', () => ({
  useTurnoCajaStore: () => ({
    estaOperando: true,
    efectivoDisponible: 1000,
    cargarTurnoActivo: vi.fn(),
  }),
}))

const pizza: Producto = {
  id: 'pizza',
  nombre: 'Pizza individual',
  precio_unitario: 90,
  tipo: 'A',
  imagen: null,
  sucursal_id: 's1',
  descripcion: null,
  es_combo: false,
}

const mockProductos = vi.mocked(obtenerProductos)
const mockCompletar = vi.mocked(pagosApi.completarPago)

/** Arma un pedido con una pizza y lo cobra en efectivo por lo que marca la pantalla. */
async function cobrarPizza() {
  const wrapper = shallowMount(CajaComponent)
  await flushPromises()
  wrapper.findComponent(ProductoCard).vm.$emit('agregar', pizza)
  await flushPromises()
  const ticket = wrapper.findComponent(TicketPanel)
  ticket.vm.$emit('actualizar-nombre', 'Ana')
  ticket.vm.$emit('pagar')
  await flushPromises()
  const modal = wrapper.findComponent(PaymentModal)
  const total = modal.props('totalToPay') as number
  modal.vm.$emit('pago-exitoso', [{ id: 'p1', method: 'Efectivo', amount: total }], null, 0, 0, 0)
  await flushPromises()
  return wrapper
}

describe('CajaComponent: cobro rechazado por precio cambiado (C2)', () => {
  beforeEach(() => {
    notify.mockReset()
    mockCompletar.mockReset()
    mockProductos.mockReset()
  })

  it('muestra el mensaje del backend, refresca precios y deja volver a cobrar', async () => {
    mockProductos
      .mockResolvedValueOnce([pizza])
      .mockResolvedValueOnce([{ ...pizza, precio_unitario: 95 }])
    mockCompletar.mockRejectedValueOnce({
      statusCode: 409,
      code: 'PRECIO_CAMBIADO',
      message: 'El precio de «Pizza individual» cambió a $95.00. Actualiza el pedido.',
    })

    const wrapper = await cobrarPizza()

    expect(mockCompletar).toHaveBeenCalledTimes(1)
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'El precio de «Pizza individual» cambió a $95.00. Actualiza el pedido.',
      }),
    )
    expect(mockProductos).toHaveBeenCalledTimes(2)
    // El pedido sigue abierto, ya con el precio nuevo para el siguiente cobro.
    expect(wrapper.findComponent(PaymentModal).props('totalToPay')).toBe(95)
    const items = wrapper.findComponent(TicketPanel).props('items') as { producto: Producto }[]
    expect(items[0]?.producto.precio_unitario).toBe(95)
  })

  it('un error que no es de catálogo no recarga productos', async () => {
    mockProductos.mockResolvedValue([pizza])
    mockCompletar.mockRejectedValueOnce({
      statusCode: 409,
      code: 'STOCK_INSUFICIENTE',
      message: 'No hay stock suficiente de «Harina» para completar la venta.',
    })

    await cobrarPizza()

    expect(mockProductos).toHaveBeenCalledTimes(1)
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Error al procesar el pago' }),
    )
  })
})
