import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useRegistrationStore } from '@/stores/registration'
import { useAccessControlStore } from '@/stores/accessControl'
import { useAuthStore } from '@/stores/auth'
import { fetchActivos, fetchPulseras } from '@/api/onboardingClient'
import { productosApi } from '@/api/productosApi'

vi.mock('@/api/onboardingClient', () => ({
  postOnboarding: vi.fn(),
  fetchActivos: vi.fn(),
  fetchPulseras: vi.fn(),
  fetchEstadoPulsera: vi.fn(),
}))

vi.mock('@/api/productosApi', () => ({
  productosApi: { obtenerPreciosEstancia: vi.fn() },
}))

const PULSERAS = [
  { id: 'p1', pulseraRfid: 'WK-0000001' },
  { id: 'p2', pulseraRfid: 'WK-0000002' },
  { id: 'p3', pulseraRfid: 'WK-0000003' },
]

function iniciarSesion() {
  const auth = useAuthStore()
  auth.user = {
    id: 'u1',
    name: 'Cajero',
    email: 'cajero@test.com',
    roles: ['Cajero'],
    branchId: 'suc-1',
    branchName: 'Centro',
    permissions: ['estancias:checkin'],
  }
}

function errorHttp(statusCode: number) {
  return Object.assign(new Error(`HTTP ${statusCode}`), { statusCode })
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(fetchPulseras)
    .mockReset()
    .mockResolvedValue(PULSERAS.map((p) => ({ ...p })))
  vi.mocked(fetchActivos).mockReset().mockResolvedValue([])
  vi.mocked(productosApi.obtenerPreciosEstancia)
    .mockReset()
    .mockResolvedValue({
      id: 'prod-1',
      config_estancia: [{ min_horas: 1, max_horas: 5, precio: 100 }],
    })
  iniciarSesion()
})

describe('registro de entrada: carga propia de pulseras (A14)', () => {
  it('sin estado previo (URL directa / F5) carga pulseras y tarifas por sí mismo', async () => {
    const store = useRegistrationStore()
    expect(store.pulseras).toHaveLength(0)

    await store.cargarDatosIniciales()

    expect(fetchPulseras).toHaveBeenCalledWith('suc-1')
    expect(productosApi.obtenerPreciosEstancia).toHaveBeenCalledTimes(1)
    expect(store.pulseras).toHaveLength(3)
    // Con 3 pulseras libres ya se puede agregar más de un niño.
    expect(store.maxChildrenAllowed).toBe(2)
    expect(store.isLoadingInicial).toBe(false)
    expect(store.errorPulseras).toBeNull()
  })

  it('no repite la petición si Control de Acceso acaba de cargar las pulseras', async () => {
    const acceso = useAccessControlStore()
    await acceso.loadActivos()
    expect(fetchPulseras).toHaveBeenCalledTimes(1)

    const store = useRegistrationStore()
    await store.cargarDatosIniciales()

    expect(fetchPulseras).toHaveBeenCalledTimes(1)
    expect(store.pulseras).toHaveLength(3)
  })

  it('dos cargas simultáneas comparten una sola petición', async () => {
    const acceso = useAccessControlStore()
    await Promise.all([acceso.asegurarPulserasCargadas(), acceso.asegurarPulserasCargadas()])
    expect(fetchPulseras).toHaveBeenCalledTimes(1)
  })

  it('si la carga falla expone el error y permite reintentar', async () => {
    vi.mocked(fetchPulseras).mockRejectedValueOnce(errorHttp(500))
    const store = useRegistrationStore()

    await store.cargarDatosIniciales()
    expect(store.errorPulseras).toBeTruthy()
    expect(store.pulseras).toHaveLength(0)

    await store.cargarDatosIniciales()
    expect(store.errorPulseras).toBeNull()
    expect(store.pulseras).toHaveLength(3)
  })

  it('tras completar un registro, las pulseras asignadas dejan de ofrecerse', () => {
    const acceso = useAccessControlStore()
    acceso.pulserasDisponibles = PULSERAS.map((p) => ({ ...p }))
    acceso.descartarPulseras(['p1'])
    expect(acceso.pulserasDisponibles.map((p) => p.id)).toEqual(['p2', 'p3'])
  })
})
