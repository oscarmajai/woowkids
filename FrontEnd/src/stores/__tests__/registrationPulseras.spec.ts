import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useRegistrationStore } from '@/stores/registration'
import { useAccessControlStore } from '@/stores/accessControl'
import { useAuthStore } from '@/stores/auth'
import { fetchActivos, fetchEstadoPulsera, fetchPulseras } from '@/api/onboardingClient'
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
  vi.mocked(fetchEstadoPulsera).mockReset()
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

describe('registro de entrada: validación de pulsera escaneada (B14)', () => {
  async function storeConNinos() {
    const store = useRegistrationStore()
    await store.cargarDatosIniciales()
    store.children[0].name = 'Niño Uno'
    store.children[0].age = 5
    store.saveChild(0)
    store.addChild()
    store.children[1].name = 'Niño Dos'
    store.children[1].age = 6
    store.saveChild(1)
    return store
  }

  it('una pulsera libre se asigna sin consultar al servidor', async () => {
    const store = await storeConNinos()
    const res = await store.asignarPulseraEscaneada(store.children[0].id, 'WK-0000001')

    expect(res).toEqual({ ok: true, pulseraId: 'p1' })
    expect(store.children[0].rfidBracelet).toBe('p1')
    expect(fetchEstadoPulsera).not.toHaveBeenCalled()
  })

  it('al terminar el registro se sigue mostrando el código de la pulsera, no su id', async () => {
    const store = await storeConNinos()
    await store.asignarPulseraEscaneada(store.children[0].id, 'WK-0000001')
    // Al completar, la pulsera sale de las disponibles (descartarPulseras).
    useAccessControlStore().descartarPulseras(['p1'])

    expect(store.etiquetaPulsera('p1')).toBe('WK-0000001')
  })

  it('una pulsera en uso por otro niño se reporta como asignada, no como inexistente', async () => {
    vi.mocked(fetchEstadoPulsera).mockResolvedValue({
      id: 'p9',
      pulseraRfid: 'WK-0000009',
      activo: true,
      usada: true,
      estado: 'usada',
    })
    const store = await storeConNinos()

    const res = await store.validarPulseraEscaneada(store.children[0].id, 'WK-0000009')

    expect(fetchEstadoPulsera).toHaveBeenCalledWith('suc-1', 'WK-0000009')
    expect(res).toEqual({
      ok: false,
      mensaje: 'La pulsera "WK-0000009" ya está asignada a otro niño.',
    })
  })

  it('una pulsera inexistente (404) se reporta como que no existe', async () => {
    vi.mocked(fetchEstadoPulsera).mockRejectedValue(errorHttp(404))
    const store = await storeConNinos()

    const res = await store.validarPulseraEscaneada(store.children[0].id, 'WK-0000099')

    expect(res).toEqual({
      ok: false,
      mensaje: 'La pulsera "WK-0000099" no existe en esta sucursal.',
    })
  })

  it('una pulsera desactivada se reporta como desactivada', async () => {
    vi.mocked(fetchEstadoPulsera).mockResolvedValue({
      id: 'p8',
      pulseraRfid: 'WK-0000008',
      activo: false,
      usada: false,
      estado: 'inactiva',
    })
    const store = await storeConNinos()

    const res = await store.validarPulseraEscaneada(store.children[0].id, 'WK-0000008')

    expect(res).toEqual({ ok: false, mensaje: 'La pulsera "WK-0000008" está desactivada.' })
  })

  it('una pulsera ya asignada a otro niño del mismo registro se rechaza', async () => {
    const store = await storeConNinos()
    await store.asignarPulseraEscaneada(store.children[0].id, 'WK-0000001')

    const res = await store.asignarPulseraEscaneada(store.children[1].id, 'WK-0000001')

    expect(res.ok).toBe(false)
    expect(store.children[1].rfidBracelet).toBe('')
  })

  it('si la lista local está desactualizada y el servidor la da por libre, se asigna', async () => {
    vi.mocked(fetchEstadoPulsera).mockResolvedValue({
      id: 'p7',
      pulseraRfid: 'WK-0000007',
      activo: true,
      usada: false,
      estado: 'disponible',
    })
    const store = await storeConNinos()

    const res = await store.asignarPulseraEscaneada(store.children[0].id, 'WK-0000007')

    expect(res).toEqual({ ok: true, pulseraId: 'p7' })
    expect(store.pulseras.some((p) => p.id === 'p7')).toBe(true)
  })

  it('un fallo de red no se confunde con pulsera inexistente', async () => {
    vi.mocked(fetchEstadoPulsera).mockRejectedValue(errorHttp(500))
    const store = await storeConNinos()

    const res = await store.validarPulseraEscaneada(store.children[0].id, 'WK-0000005')

    expect(res).toEqual({
      ok: false,
      mensaje: 'No se pudo verificar la pulsera "WK-0000005". Intenta de nuevo.',
    })
  })
})
