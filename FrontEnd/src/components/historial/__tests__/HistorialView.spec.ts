import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import HistorialView from '@/components/historial/HistorialView.vue'
import ReimprimirComprobanteDialog from '@/components/control-acceso/ReimprimirComprobanteDialog.vue'
import { obtenerEstadisticas, obtenerHistorial } from '@/services/historialService'
import type { ITransaccion } from '@/types/transaccion'

/**
 * El historial es por sucursal: el AdministradorSistema en "Todas las
 * sucursales" no tiene una elegida, así que no se consulta y se pide elegir una.
 */

const auth = vi.hoisted(() => ({
  currentBranchId: null as string | null,
  permisos: { 'estancias:checkin': true } as Record<string, boolean>,
  hasPermission: (codigo: string) => auth.permisos[codigo] ?? true,
  hasRole: () => true,
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('@/services/historialService', () => ({
  obtenerHistorial: vi.fn(async () => []),
  obtenerEstadisticas: vi.fn(async () => ({
    total_ventas: 0,
    total_ordenes: 0,
    ticket_promedio: 0,
  })),
  exportarHistorial: vi.fn(),
}))
vi.mock('@/services/turnoCajaService', () => ({
  turnoCajaService: { obtenerCajas: vi.fn(async () => []) },
}))
vi.mock('@/stores/metodos_pago', () => ({
  useMetodosPagoStore: () => ({ metodos: [{ id: 'mp', nombre: 'Efectivo' }], cargar: vi.fn() }),
}))
vi.mock('@/composables/useCancelarComanda', () => ({
  useCancelarComanda: () => ({ cancelarComanda: vi.fn(), devolverComanda: vi.fn() }),
}))

const montar = () =>
  mount(HistorialView, {
    global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
  })

describe('HistorialView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(obtenerHistorial).mockClear()
    vi.mocked(obtenerEstadisticas).mockClear()
  })

  it('sin sucursal elegida no consulta y pide elegir una', async () => {
    auth.currentBranchId = null
    const wrapper = montar()
    await flushPromises()

    expect(obtenerHistorial).not.toHaveBeenCalled()
    expect(obtenerEstadisticas).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('elige una en el selector')
  })

  it('con sucursal elegida carga el historial', async () => {
    auth.currentBranchId = 'suc-1'
    const wrapper = montar()
    await flushPromises()

    expect(obtenerHistorial).toHaveBeenCalledTimes(1)
    expect(obtenerEstadisticas).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).not.toContain('elige una en el selector')
  })

  describe('imprimir ticket normal o con QR', () => {
    const fila = (cambios: Partial<ITransaccion>): ITransaccion => ({
      tipo_origen: 'estancia',
      referencia_id: 'reg-1',
      titulo: 'Laura Méndez',
      total_final: 150,
      estado_actual: 'A',
      sucursal_id: 'suc-1',
      creado: '2026-10-08T15:00:00Z',
      creado_por: null,
      metodos_pago: [],
      comanda_id: null,
      ticket_numero: null,
      ...cambios,
    })

    async function abrirMenuImprimir(filas: ITransaccion[]) {
      auth.currentBranchId = 'suc-1'
      vi.mocked(obtenerHistorial).mockResolvedValueOnce(filas)
      const wrapper = mount(HistorialView, {
        attachTo: document.body,
        global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
      })
      await flushPromises()
      await wrapper.get('[data-test="imprimir-no-comanda"]').trigger('click')
      await flushPromises()
      return wrapper
    }

    const opcion = (nombre: string) =>
      document.body.querySelector<HTMLElement>(`[data-test="${nombre}"]`)

    beforeEach(() => {
      auth.permisos = { 'estancias:checkin': true }
      document.body.innerHTML = ''
    })

    it('una estancia con niños dentro ofrece el ticket normal y el ticket con QR', async () => {
      const wrapper = await abrirMenuImprimir([fila({ estado_actual: 'A' })])
      expect(opcion('imprimir-ticket-normal')).not.toBeNull()
      const qr = opcion('imprimir-ticket-qr')
      expect(qr).not.toBeNull()
      expect(qr?.getAttribute('aria-disabled')).not.toBe('true')
      wrapper.unmount()
    })

    it('si la estancia ya cerró, el QR queda deshabilitado y explica por qué', async () => {
      const wrapper = await abrirMenuImprimir([fila({ estado_actual: 'C' })])
      const qr = opcion('imprimir-ticket-qr')
      expect(qr?.getAttribute('aria-disabled')).toBe('true')
      expect(qr?.textContent).toContain('Solo con niños dentro')
      expect(opcion('imprimir-ticket-normal')?.getAttribute('aria-disabled')).not.toBe('true')
      wrapper.unmount()
    })

    it('sin permiso de check-in no se puede reimprimir con QR', async () => {
      auth.permisos = { 'estancias:checkin': false }
      const wrapper = await abrirMenuImprimir([fila({ estado_actual: 'A' })])
      const qr = opcion('imprimir-ticket-qr')
      expect(qr?.getAttribute('aria-disabled')).toBe('true')
      expect(qr?.textContent).toContain('Sin permiso')
      wrapper.unmount()
    })

    it('elegir el ticket con QR abre la reimpresión de ese registro', async () => {
      const wrapper = await abrirMenuImprimir([fila({ referencia_id: 'reg-77' })])
      expect(wrapper.findComponent(ReimprimirComprobanteDialog).exists()).toBe(false)

      opcion('imprimir-ticket-qr')?.click()
      await flushPromises()

      const dialogo = wrapper.findComponent(ReimprimirComprobanteDialog)
      expect(dialogo.exists()).toBe(true)
      expect(dialogo.props('registroId')).toBe('reg-77')
      wrapper.unmount()
    })

    it('un evento solo ofrece el ticket normal, sin opción de QR', async () => {
      const wrapper = await abrirMenuImprimir([fila({ tipo_origen: 'reservacion' })])
      expect(opcion('imprimir-ticket-normal')).not.toBeNull()
      expect(opcion('imprimir-ticket-qr')).toBeNull()
      wrapper.unmount()
    })
  })
})
