import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import MethodSelector from './MethodSelector.vue'
import PaymentKeypad from './PaymentKeypad.vue'
import PaymentModal from './PaymentModal.vue'
import { useAuthStore } from '@/stores/auth'
import { useLealtadStore } from '@/stores/lealtad'
import type { MetodosPago } from '@/types/metodos_pago'
import type { ConfiguracionCanje } from '@/types/lealtad'

// $q.notify solo existe con el plugin Notify instalado en la app; aquí se
// simula para poder revisar los avisos que da el modal.
const notify = vi.hoisted(() => vi.fn())
vi.mock('quasar', async (importOriginal) => {
  const original = await importOriginal<typeof import('quasar')>()
  return { ...original, useQuasar: () => ({ ...original.useQuasar(), notify }) }
})

/**
 * A6 (E2E 2026-10-03): el cajero no podía canjear puntos porque la
 * configuración de lealtad le respondía 403; el modal mostraba "$ c/u",
 * "Solo puede aplicar hasta $0.00" y tomaba el mínimo de canje como 0.
 */
const METODOS: MetodosPago[] = [
  {
    id: 'e',
    nombre: 'Efectivo',
    descripcion: null,
    tipo: 'E',
    comision_porcentaje: null,
    requiere_referencia: false,
    activo: true,
  },
  {
    id: 'l',
    nombre: 'Lealtad',
    descripcion: null,
    tipo: 'L',
    comision_porcentaje: null,
    requiere_referencia: false,
    activo: true,
  },
]

const CONFIG: ConfiguracionCanje = {
  sucursal_id: 'suc-1',
  activo: true,
  valor_punto: 1,
  minimo_canje: 50,
}

const montar = () =>
  mount(PaymentModal, {
    props: { modelValue: true, totalToPay: 100, metodosPago: METODOS },
    global: { stubs: { QDialog: { template: '<div><slot /></div>' } } },
  })

type Wrapper = ReturnType<typeof montar>

/** Monta el modal como cajero, con el saldo y la configuración indicados. */
const prepararCobro = async (
  saldo: number,
  config: () => Promise<ConfiguracionCanje>,
): Promise<{ wrapper: Wrapper; lealtad: ReturnType<typeof useLealtadStore> }> => {
  const wrapper = montar()
  useAuthStore().user = {
    id: 'u1',
    name: 'Cajero',
    email: 'c@test.com',
    roles: ['Cajero'],
    branchId: 'suc-1',
    branchName: 'Sucursal',
    permissions: ['lealtad:ver_saldo', 'lealtad:redimir'],
  }
  const lealtad = useLealtadStore()
  vi.spyOn(lealtad, 'cargarSaldo').mockResolvedValue({
    sucursal_id: 'suc-1',
    celular: '3398765432',
    saldo,
    por_vencer: 0,
  })
  vi.spyOn(lealtad, 'cargarConfiguracionCanje').mockImplementation(config)
  vi.spyOn(lealtad, 'cargarConfiguracion')

  await wrapper.findComponent({ name: 'QInput' }).vm.$emit('update:modelValue', '3398765432')
  await flushPromises()
  return { wrapper, lealtad }
}

/** Selecciona Lealtad y captura un monto, como "Aplicar puntos". */
const aplicarPuntos = async (wrapper: Wrapper, monto: number) => {
  await wrapper.findComponent(MethodSelector).vm.$emit('update:modelValue', 'Lealtad')
  await wrapper.findComponent(PaymentKeypad).vm.$emit('add-payment', monto)
  await wrapper.vm.$nextTick()
}

describe('PaymentModal · canje de puntos (A6)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    notify.mockReset()
  })

  it('lee la configuración de canje (no la de administración) y aplica los puntos', async () => {
    const { wrapper, lealtad } = await prepararCobro(52, () => Promise.resolve(CONFIG))

    expect(lealtad.cargarConfiguracionCanje).toHaveBeenCalledWith('suc-1')
    expect(lealtad.cargarConfiguracion).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('52 pts disponibles · $1.00 c/u')

    await aplicarPuntos(wrapper, 50)

    expect(wrapper.text()).toContain('Descuento por puntos')
    expect(wrapper.text()).toContain('−$50.00')
  })

  it('si la configuración falla, deshabilita el canje con un mensaje claro', async () => {
    const { wrapper } = await prepararCobro(52, () =>
      Promise.reject({ statusCode: 403, code: 'FORBIDDEN', message: 'Sin permiso' }),
    )

    expect(wrapper.text()).toContain(
      'Canje no disponible: no se pudo cargar la configuración de puntos.',
    )
    expect(wrapper.text()).not.toContain('c/u')

    await aplicarPuntos(wrapper, 50)

    expect(wrapper.text()).not.toContain('Descuento por puntos')
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        message: 'Canje no disponible: no se pudo cargar la configuración de puntos.',
      }),
    )
    expect(notify).not.toHaveBeenCalledWith(
      expect.objectContaining({ message: expect.stringContaining('$0.00') }),
    )
  })

  it('sin configuración en la sucursal (404) lo explica', async () => {
    const { wrapper } = await prepararCobro(52, () =>
      Promise.reject({ statusCode: 404, code: 'NOT_FOUND', message: 'No encontrado' }),
    )

    expect(wrapper.text()).toContain(
      'Canje no disponible: la sucursal no tiene configurado el programa de puntos.',
    )
  })

  it('respeta el mínimo de canje de la sucursal en vez de tomarlo como 0', async () => {
    const { wrapper } = await prepararCobro(6, () => Promise.resolve(CONFIG))

    expect(wrapper.text()).toContain('Mínimo para canjear: 50 pts')

    await aplicarPuntos(wrapper, 6)

    expect(wrapper.text()).not.toContain('Descuento por puntos')
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ message: 'Mínimo para canjear: 50 pts.' }),
    )
  })

  it('si falla el saldo, igual muestra la configuración leída', async () => {
    const wrapper = montar()
    useAuthStore().user = {
      id: 'u1',
      name: 'Cajero',
      email: 'c@test.com',
      roles: ['Cajero'],
      branchId: 'suc-1',
      branchName: 'Sucursal',
      permissions: [],
    }
    const lealtad = useLealtadStore()
    vi.spyOn(lealtad, 'cargarSaldo').mockRejectedValue({ statusCode: 404 })
    vi.spyOn(lealtad, 'cargarConfiguracionCanje').mockResolvedValue(CONFIG)

    await wrapper.findComponent({ name: 'QInput' }).vm.$emit('update:modelValue', '3398765432')
    await flushPromises()

    // Saldo 0 por 404 (cliente sin cuenta): no hay nada que canjear ni error.
    expect(wrapper.text()).not.toContain('Canje no disponible')
    expect(wrapper.text()).not.toContain('pts disponibles')
  })
})
