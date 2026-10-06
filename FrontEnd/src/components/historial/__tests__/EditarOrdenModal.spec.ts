import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import EditarOrdenModal from '../EditarOrdenModal.vue'
import type { DetalleOrden, DetalleProducto } from '@/api/historialApi'
import { obtenerDetalleOrden } from '@/services/historialService'
import { modificarDetallesComanda } from '@/services/comandaService'

const notify = vi.fn()
const dialog = vi.fn(() => ({ onOk: (cb: () => void) => cb() }))

vi.mock('quasar', async (original) => ({
  ...(await original<typeof import('quasar')>()),
  useQuasar: () => ({ notify, dialog }),
}))
vi.mock('@/services/historialService', () => ({ obtenerDetalleOrden: vi.fn() }))
vi.mock('@/services/comandaService', () => ({ modificarDetallesComanda: vi.fn() }))
vi.mock('@/composables/useCancelarComanda', () => ({
  useCancelarComanda: () => ({ cancelarComanda: vi.fn() }),
}))

const mockDetalle = vi.mocked(obtenerDetalleOrden)
const mockModificar = vi.mocked(modificarDetallesComanda)

function detalle(id: string, nombre: string, extra: Partial<DetalleProducto> = {}) {
  return {
    id,
    producto_nombre: nombre,
    cantidad: 1,
    precio_unitario: 0,
    importe: 0,
    notas_especiales: null,
    nombre_combo_padre: null,
    ...extra,
  }
}

const combo = { nombre_combo_padre: 'Combo Hot dog' }
const ORDEN: DetalleOrden = {
  tipo_origen: 'comanda',
  referencia_id: 'cmd',
  titulo: 'A15',
  total_final: 240,
  estado_actual: 'P',
  fecha_hora: null,
  motivo_cancelacion: null,
  creado_por_nombre: null,
  metodos_pago: [],
  comanda_id: 'cmd',
  ticket_numero: 'A15',
  nombre_cliente: null,
  modificado: 'v1',
  detalles: [
    detalle('c1', 'Combo Hot dog', { precio_unitario: 120, importe: 120 }),
    detalle('c2', 'Combo Hot dog', {
      precio_unitario: 120,
      importe: 120,
      notas_especiales: 'el segundo',
    }),
    detalle('h1', 'Hot dog', { ...combo, detalle_padre_id: 'c1' }),
    detalle('h2', 'Refresco', { ...combo, detalle_padre_id: 'c1' }),
    detalle('h3', 'Hot dog', { ...combo, detalle_padre_id: 'c2' }),
    detalle('h4', 'Refresco', { ...combo, detalle_padre_id: 'c2' }),
  ],
}

async function quitarSegundoCombo() {
  const wrapper = shallowMount(EditarOrdenModal, { props: { comandaId: 'cmd' } })
  await flushPromises()
  const filas = wrapper.findAll('.edit-list__row')
  expect(filas).toHaveLength(2)
  await filas[1]!.trigger('click')
  const quitar = wrapper
    .findAllComponents({ name: 'QBtn' })
    .find((b) => b.props('label') === 'Quitar productos')
  quitar!.vm.$emit('click')
  await flushPromises()
  return wrapper
}

describe('EditarOrdenModal', () => {
  beforeEach(() => {
    notify.mockReset()
    mockDetalle.mockReset()
    mockModificar.mockReset()
    mockDetalle.mockResolvedValue(structuredClone(ORDEN))
  })

  it('quita solo el combo elegido con sus productos y manda la versión leída', async () => {
    mockModificar.mockResolvedValueOnce({} as never)
    await quitarSegundoCombo()

    expect(mockModificar).toHaveBeenCalledWith('cmd', ['c2', 'h3', 'h4'], undefined, {
      modificadoEsperado: 'v1',
    })
  })

  it('si la orden cambió en otra pestaña, la recarga y avisa', async () => {
    mockModificar.mockRejectedValueOnce({
      statusCode: 409,
      code: 'COMANDA_MODIFICADA',
      message: 'La orden cambió mientras la editabas.',
    })
    const wrapper = await quitarSegundoCombo()

    expect(mockDetalle).toHaveBeenCalledTimes(2)
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'warning',
        message: 'La orden cambió mientras la editabas.',
      }),
    )
    expect(wrapper.emitted('close')).toBeUndefined()
  })
})
