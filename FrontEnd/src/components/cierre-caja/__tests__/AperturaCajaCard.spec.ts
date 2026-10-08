import { flushPromises, shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { QBtn, QInput, QSelect } from 'quasar'

import AperturaCajaCard from '@/components/cierre-caja/AperturaCajaCard.vue'
import BaseDialog from '@/components/ui/BaseDialog.vue'
import { turnoCajaService } from '@/services/turnoCajaService'

/**
 * Horario de trabajo al abrir turno: se preselecciona el vigente (lo calcula
 * el backend con la hora local de la sucursal), no el primero de la lista, y,
 * si se elige otro, se pide confirmar (no se bloquea: es decisión de negocio).
 * Sin cajas, el aviso no promete crear una "automáticamente".
 */

const notify = vi.fn()
vi.mock('quasar', async (original) => ({
  ...(await original<typeof import('quasar')>()),
  useQuasar: () => ({ notify }),
}))

vi.mock('@/services/turnoCajaService', () => ({
  turnoCajaService: { obtenerTurnos: vi.fn(), obtenerCajas: vi.fn() },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    currentUser: { name: 'Valeria', branchId: 's1' },
    currentBranchId: 's1',
    hasRole: () => false,
  }),
}))

const turno = reactive({
  error: null as string | null,
  cargando: false,
  estaOperando: false,
  abrirTurno: vi.fn(),
})
vi.mock('@/stores/turnoCaja', () => ({ useTurnoCajaStore: () => turno }))

const servicio = vi.mocked(turnoCajaService)

const HORARIOS = [
  { id: 'mat', nombre: 'Matutino', horaInicio: '08:00:00', horaFin: '15:00:00', vigente: false },
  { id: 'ves', nombre: 'Vespertino', horaInicio: '15:00:00', horaFin: '23:59:00', vigente: true },
]
const CAJAS = [{ id: 'c1', codigo: 'CAJA 01', nombre: 'Caja Patria 1' }]

async function montar() {
  const wrapper = shallowMount(AperturaCajaCard)
  await flushPromises()
  return wrapper
}

function selectores(wrapper: Awaited<ReturnType<typeof montar>>) {
  const [horario, caja] = wrapper.findAllComponents(QSelect)
  return { horario: horario!, caja: caja! }
}

async function llenarPinYAbrir(wrapper: Awaited<ReturnType<typeof montar>>) {
  const pin = wrapper.findAllComponents(QInput).find((i) => i.props('type') === 'password')
  pin!.vm.$emit('update:modelValue', '1234')
  await flushPromises()
  wrapper.findComponent(QBtn).vm.$emit('click')
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  turno.error = null
  turno.estaOperando = false
  servicio.obtenerTurnos.mockResolvedValue(HORARIOS)
  servicio.obtenerCajas.mockResolvedValue(CAJAS)
})

describe('AperturaCajaCard — horario de trabajo', () => {
  it('preselecciona el horario vigente, no el primero de la lista', async () => {
    const wrapper = await montar()

    expect(selectores(wrapper).horario.props('modelValue')).toBe('ves')
  })

  it('sin horario vigente no preselecciona ninguno', async () => {
    servicio.obtenerTurnos.mockResolvedValue(HORARIOS.map((h) => ({ ...h, vigente: false })))

    const wrapper = await montar()

    expect(selectores(wrapper).horario.props('modelValue')).toBeNull()
  })

  it('con el horario vigente abre sin pedir confirmación', async () => {
    const wrapper = await montar()

    await llenarPinYAbrir(wrapper)

    expect(turno.abrirTurno).toHaveBeenCalledTimes(1)
    expect(turno.abrirTurno.mock.calls[0]![3]).toBe('ves')
    expect(wrapper.findComponent(BaseDialog).props('modelValue')).toBe(false)
  })

  it('con un horario que no corresponde a la hora pide confirmar antes de abrir', async () => {
    const wrapper = await montar()
    selectores(wrapper).horario.vm.$emit('update:modelValue', 'mat')
    await flushPromises()
    expect(wrapper.find('[data-test="aviso-horario-no-vigente"]').exists()).toBe(true)

    await llenarPinYAbrir(wrapper)

    const dialogo = wrapper.findComponent(BaseDialog)
    expect(dialogo.props('modelValue')).toBe(true)
    expect(turno.abrirTurno).not.toHaveBeenCalled()

    dialogo.vm.$emit('confirm')
    await flushPromises()

    expect(turno.abrirTurno).toHaveBeenCalledTimes(1)
    expect(turno.abrirTurno.mock.calls[0]![3]).toBe('mat')
  })
})

describe('AperturaCajaCard — sin cajas registradas', () => {
  it('pide al administrador registrar una y no deja abrir', async () => {
    servicio.obtenerCajas.mockResolvedValue([])

    const wrapper = await montar()

    const aviso = wrapper.get('[data-test="aviso-sin-cajas"]').text()
    expect(aviso).toContain('Pide al administrador')
    expect(aviso).not.toContain('automáticamente')
    expect(wrapper.findComponent(QBtn).props('disable')).toBe(true)
  })
})
