import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PaymentKeypad from './PaymentKeypad.vue'
import PaymentModal from './PaymentModal.vue'
import type { MetodosPago } from '@/types/metodos_pago'

/**
 * En Pagos › "Registrar pago — Abono…" y en el Cierre de evento se puede
 * registrar un abono parcial: "Confirmar pago" no exige que el monto cubra
 * todo el saldo.
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
]

const montar = (props: Record<string, unknown> = {}) =>
  mount(PaymentModal, {
    props: {
      modelValue: true,
      totalToPay: 5029,
      metodosPago: METODOS,
      permitirLealtad: false,
      ...props,
    },
    global: { stubs: { QDialog: { template: '<div><slot /></div>' } } },
  })

const capturar = async (wrapper: ReturnType<typeof montar>, monto: number) => {
  await wrapper.findComponent(PaymentKeypad).vm.$emit('add-payment', monto)
  await wrapper.vm.$nextTick()
}

const botonConfirmar = (wrapper: ReturnType<typeof montar>) =>
  wrapper
    .findAllComponents({ name: 'QBtn' })
    .find((b) => ['Confirmar pago', 'Registrar abono'].includes(b.props('label') as string))!

describe('PaymentModal · abonos parciales', () => {
  it('por defecto exige cubrir el total', async () => {
    const wrapper = montar()
    await capturar(wrapper, 2000)
    expect(botonConfirmar(wrapper).props('disable')).toBe(true)
  })

  it('con permitirPagoParcial registra un abono menor al saldo', async () => {
    const wrapper = montar({ permitirPagoParcial: true })
    expect(botonConfirmar(wrapper).props('disable')).toBe(true) // sin monto, nada que registrar

    await capturar(wrapper, 2000)
    const boton = botonConfirmar(wrapper)
    expect(boton.props('disable')).toBe(false)
    expect(boton.props('label')).toBe('Registrar abono')

    await boton.trigger('click')
    const emitido = wrapper.emitted('pago-exitoso')
    expect(emitido).toBeTruthy()
    const pagos = emitido![0]![0] as { amount: number }[]
    expect(pagos.reduce((s, p) => s + p.amount, 0)).toBe(2000)
    expect(emitido![0]![4]).toBe(0) // sin cambio
  })

  it('con permitirPagoParcial el cobro total sigue funcionando igual', async () => {
    const wrapper = montar({ permitirPagoParcial: true })
    await capturar(wrapper, 5029)
    const boton = botonConfirmar(wrapper)
    expect(boton.props('disable')).toBe(false)
    expect(boton.props('label')).toBe('Confirmar pago')
  })
})
