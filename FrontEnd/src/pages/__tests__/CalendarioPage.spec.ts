import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CalendarioPage from '@/pages/CalendarioPage.vue'
import { reservacionesApi } from '@/api/reservacionesApi'
import { branchService } from '@/services/branchService'
import type { Reservaciones } from '@/types/reservaciones'

/**
 * A9: la vista Mes entraba en un bucle de 1,100+ GET /reservaciones en pocos
 * segundos. El rango de la carga salía de la cuadrícula, que se recalcula con
 * los eventos cargados, y el watch observaba un arreglo nuevo en cada
 * evaluación: cada respuesta disparaba otra carga.
 */

vi.mock('@/api/reservacionesApi', () => ({
  reservacionesApi: { listar: vi.fn() },
}))
vi.mock('@/services/branchService', () => ({
  branchService: {
    getBranch: vi.fn().mockRejectedValue({ statusCode: 403 }),
    getHorario: vi.fn().mockResolvedValue({ horaApertura: '10:00', horaCierre: '21:30' }),
  },
}))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ currentBranchId: 'suc-1' }),
}))
vi.mock('@/stores/turnoCaja', () => ({
  useTurnoCajaStore: () => ({ estaOperando: true }),
}))
vi.mock('@/stores/paquetes', () => ({
  usePaquetesStore: () => ({ paquetes: [{ id: 'paq-1', nombre: 'Básica' }], cargar: vi.fn() }),
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const listarMock = vi.mocked(reservacionesApi.listar)

const isoHoy = () => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Respuesta nueva en cada llamada, como el backend: arreglo y objetos nuevos. */
const reservacionDeHoy = (): Reservaciones =>
  ({
    id: 'res-1',
    sucursal_id: 'suc-1',
    tipo_evento_id: 'tip-1',
    paquete_id: 'paq-1',
    nombre_cliente: 'Gabriela',
    apellidos_cliente: 'Núñez',
    telefono_cliente: '3312345678',
    nombre_festejado: 'Sofía',
    edad_festejado: 6,
    fecha_evento: isoHoy(),
    hora_inicio: '16:00:00',
    hora_fin: '19:00:00',
    numero_personas: 12,
    saldo_pendiente: '0.00',
    estado: 'confirmada',
    activo: true,
  }) as Reservaciones

const montar = () =>
  mount(CalendarioPage, {
    global: {
      stubs: {
        // QPage exige estar dentro de un QLayout; aquí solo importa su contenido.
        QPage: { template: '<div><slot /></div>' },
        'router-link': { template: '<a><slot /></a>' },
      },
    },
  })

describe('CalendarioPage (vista Mes)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listarMock.mockReset()
    // La respuesta llega en otra vuelta del reloj, como una petición real: con
    // el bucle de A9 el contador sube sin congelar la prueba.
    listarMock.mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve([reservacionDeHoy()]), 0)),
    )
  })
  afterEach(() => vi.clearAllMocks())

  it('al montarse hace una sola petición y pinta la cuadrícula', async () => {
    const wrapper = montar()
    // Varias vueltas de microtareas y del reloj: con el bucle, cada respuesta
    // pedía otra y el contador seguía subiendo.
    for (let i = 0; i < 20; i++) await flushPromises()
    await new Promise((r) => setTimeout(r, 30))
    await flushPromises()

    expect(listarMock).toHaveBeenCalledTimes(1)
    const [sucursal, desde, hasta] = listarMock.mock.calls[0]!
    expect(sucursal).toBe('suc-1')
    // 42 celdas de lunes a domingo que contienen el mes actual.
    const inicio = new Date(`${desde}T00:00:00`)
    const fin = new Date(`${hasta}T00:00:00`)
    expect(inicio.getDay()).toBe(1)
    expect(Math.round((fin.getTime() - inicio.getTime()) / 86_400_000)).toBe(41)
    expect(wrapper.text()).toContain('Núñez')
  })

  it('cambiar de mes hace exactamente una petición más', async () => {
    const wrapper = montar()
    for (let i = 0; i < 10; i++) await flushPromises()
    expect(listarMock).toHaveBeenCalledTimes(1)

    const siguiente = wrapper
      .findAll('button')
      .find((b) => b.attributes('aria-label') === 'Periodo siguiente')
    expect(siguiente, 'no se encontró el botón Siguiente').toBeTruthy()
    await siguiente!.trigger('click')
    for (let i = 0; i < 10; i++) await flushPromises()

    expect(listarMock).toHaveBeenCalledTimes(2)
    expect(listarMock.mock.calls[1]![1]).not.toBe(listarMock.mock.calls[0]![1])
  })

  it('pide el horario por el endpoint que la cajera sí puede leer (B18)', async () => {
    montar()
    for (let i = 0; i < 5; i++) await flushPromises()
    expect(branchService.getHorario).toHaveBeenCalledWith('suc-1')
    // GET /sucursales/{id} exige sucursales:ver y a la cajera le da 403.
    expect(branchService.getBranch).not.toHaveBeenCalled()
  })
})
