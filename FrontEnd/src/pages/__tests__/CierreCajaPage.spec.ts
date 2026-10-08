import { shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import CierreCajaPage from '@/pages/CierreCajaPage.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import type { VentaPorMetodo } from '@/types/turnoCaja'

/**
 * Hub del turno operando:
 * - Muestra el efectivo esperado y las ventas por método (no solo fondo y
 *   retiros), y avisa si la caja quedó en negativo.
 * - "Ingreso de efectivo" y "Retiro parcial" solo para quien tiene el
 *   permiso (el Administrador abre y cierra su turno, pero no tiene ninguno de
 *   los dos).
 * - El turno se identifica con el nombre de la caja, no solo "CAJA 01".
 */

const permisos = new Set<string>()

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    currentBranchId: 's1',
    user: { name: 'Diego' },
    hasPermission: (p: string) => permisos.has(p),
  }),
}))

const turno = reactive({
  sinTurno: false,
  cargando: false,
  turnoId: 't1',
  estaOperando: true,
  enConteo: false,
  esperandoRevision: false,
  balanceRevelado: false,
  estaCerrado: false,
  mostrarDialogAdmin: false,
  mostrarDialogAutorizacion: false,
  cajeroNombre: 'Diego',
  terminal: 'CAJA 01',
  cajaNombre: 'Caja Patria 1',
  fechaApertura: null as string | null,
  fondoInicial: 2000,
  totalRetiros: 12000,
  totalIngresos: 0,
  efectivoDisponible: 1500,
  efectivoEsperado: 1500 as number | null,
  cajaEnNegativo: false,
  observacionesApertura: '',
  ventasPorMetodo: [] as VentaPorMetodo[],
  desgloseEfectivo: { billetes: [], monedas: [], total: 0 },
  metodosPago: [],
  totalContadoDeclarado: null,
  error: null,
  cargarTurnoActivo: vi.fn(),
  iniciarConteo: vi.fn(),
  cancelarConteo: vi.fn(),
  enviarConteo: vi.fn(),
  reiniciarCicloTurno: vi.fn(),
})

vi.mock('@/stores/turnoCaja', () => ({ useTurnoCajaStore: () => turno }))

function montar() {
  // q-page queda como stub: se renderiza su slot para ver el contenido.
  return shallowMount(CierreCajaPage, { global: { renderStubDefaultSlot: true } })
}

beforeEach(() => {
  permisos.clear()
  turno.efectivoDisponible = 1500
  turno.efectivoEsperado = 1500
  turno.cajaEnNegativo = false
  turno.observacionesApertura = ''
  turno.ventasPorMetodo = []
})

describe('CierreCajaPage — hub del turno', () => {
  it('el cajero ve ingreso y retiro', () => {
    permisos.add('turnos_caja:ingreso_efectivo')
    permisos.add('retiros_parciales:crear')

    const wrapper = montar()

    expect(wrapper.find('[data-test="hub-ingreso"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="hub-retiro"]').exists()).toBe(true)
  })

  it('sin los permisos (Administrador) no se ofrecen ingreso ni retiro', () => {
    const wrapper = montar()

    expect(wrapper.find('[data-test="hub-ingreso"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="hub-retiro"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Cierre de caja')
  })

  it('muestra el efectivo esperado y las ventas por método', () => {
    turno.ventasPorMetodo = [
      { metodo: 'efectivo', label: 'Efectivo', total: 880 },
      { metodo: 'tarjeta', label: 'Tarjeta', total: 300 },
      { metodo: 'cupones', label: 'Cupones', total: 0 },
    ]

    const wrapper = montar()

    expect(wrapper.get('[data-test="hub-efectivo-esperado"]').text()).toContain('$1,500.00')
    const ventas = wrapper.findAll('[data-test="hub-venta-metodo"]').map((v) => v.text())
    expect(ventas).toHaveLength(2)
    expect(ventas[0]).toContain('Ventas en efectivo')
    expect(ventas[0]).toContain('$880.00')
    expect(ventas[1]).toContain('Ventas en tarjeta')
    expect(wrapper.find('[data-test="alerta-caja-negativa"]').exists()).toBe(false)
  })

  it('avisa cuando la caja está en negativo', () => {
    turno.efectivoDisponible = -1685
    turno.cajaEnNegativo = true

    const wrapper = montar()

    const alerta = wrapper.get('[data-test="alerta-caja-negativa"]')
    expect(alerta.text()).toContain('La caja está en negativo')
    expect(alerta.text()).toContain('-$1,685.00')
    expect(alerta.text()).toContain('Avisa al administrador')
  })

  it('sin el esperado del backend (cajero) el conteo sigue a ciegas', () => {
    // El backend omite efectivo_esperado y ventas_por_metodo a quien no
    // revisa arqueos; el store cae a un cálculo local que el hub no muestra.
    turno.efectivoEsperado = null
    turno.efectivoDisponible = -1685
    turno.cajaEnNegativo = true

    const wrapper = montar()

    expect(wrapper.find('[data-test="hub-efectivo-esperado"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="alerta-caja-negativa"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="hub-venta-metodo"]')).toHaveLength(0)
  })

  it('muestra las notas de apertura', () => {
    turno.observacionesApertura = 'Fondo con monedas de $10'

    expect(montar().text()).toContain('Fondo con monedas de $10')
  })

  it('el turno se identifica con el nombre de la caja', () => {
    const header = montar().findComponent(PageHeader)

    expect(header.props('subtitle')).toContain('Caja Patria 1 (CAJA 01)')
  })
})
