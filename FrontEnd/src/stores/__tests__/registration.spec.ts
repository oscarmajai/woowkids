import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useRegistrationStore } from '@/stores/registration'
import { useAuthStore } from '@/stores/auth'
import { postOnboarding } from '@/api/onboardingClient'
import type { PrecioEstancia } from '@/types/producto'
import type { AvisoPrivacidad } from '@/types/privacidad'
import { privacidadService } from '@/services/privacidadService'

vi.mock('@/api/onboardingClient', () => ({
  postOnboarding: vi.fn(),
}))

vi.mock('@/services/privacidadService', () => ({
  privacidadService: { obtenerVigente: vi.fn() },
}))

const AVISO: AvisoPrivacidad = {
  version: 4,
  vigenteDesde: '2026-10-03T18:00:00Z',
  fechaVigencia: '2026-10-03',
  nombreComercial: 'Woow Kids',
  textoIntegral: '# Integral',
  textoSimplificado: '# Simplificado',
}

const PRODUCTO: PrecioEstancia = {
  id: 'prod-1',
  config_estancia: [{ min_horas: 1, max_horas: 1, precio: 100 }],
}

function prepararRegistroListo({ aceptaAviso = true } = {}) {
  const store = useRegistrationStore()
  const auth = useAuthStore()

  auth.user = {
    id: 'u1',
    name: 'Cajero',
    email: 'cajero@test.com',
    roles: ['Cajero'],
    branchId: 'suc-1',
    branchName: 'Centro',
    permissions: [],
  }

  store.productoBase = PRODUCTO
  store.children[0].name = 'Niño Uno'
  store.children[0].age = 5
  store.saveChild(0)
  store.tutor.fullName = 'Ana Gómez'
  store.tutor.phone = '3312345678'
  store.tutor.inePhoto = new File(['x'], 'ine.jpg')
  store.tutor.arrivalPhotos = [new File(['x'], 'llegada.jpg')]
  store.avisoPrivacidad = AVISO
  store.aceptaAvisoPrivacidad = aceptaAviso

  return store
}

describe('registration store: pagos en completeRegistration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(postOnboarding).mockReset()
    vi.mocked(postOnboarding).mockResolvedValue({
      registroId: 'r1',
      total: 100,
      pagado: 100,
      estado: 'activo',
      codigoAccesoPadres: 'codigo-opaco-r1',
    })
  })

  it('cuando los puntos cubren todo el total, envía pagos: [] sin ningún UUID fijo', async () => {
    const store = prepararRegistroListo()

    await store.proceedToRFID([], 0, 100, 100)
    await store.completeRegistration()

    expect(postOnboarding).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(postOnboarding).mock.calls[0][0]
    expect(payload.pagos).toEqual([])
    expect(JSON.stringify(payload)).not.toContain('b827363b-6453-40e4-9536-f7a004711f91')
  })

  it('si los pagos no cuadran con el total, no envía nada al backend', async () => {
    const store = prepararRegistroListo()

    // Total es 100; este pago solo cubre 50 y no hay descuento de puntos.
    await store.proceedToRFID([{ metodoPagoId: 'm-1', monto: 50 }], 0, 0)
    await store.completeRegistration()

    expect(postOnboarding).not.toHaveBeenCalled()
    expect(store.submitError).toBeTruthy()
  })

  it('guarda el código opaco del portal de padres que devuelve el backend (A17)', async () => {
    const store = prepararRegistroListo()

    await store.proceedToRFID([], 0, 100, 100)
    await store.completeRegistration()

    expect(store.codigoAccesoPadres).toBe('codigo-opaco-r1')
    expect(store.codigoAccesoPadres).not.toBe(store.registroId)

    store.reset()
    expect(store.codigoAccesoPadres).toBe('')
  })
})

describe('registration store: referencia de pago (N8)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(postOnboarding).mockReset()
  })

  it('envía la referencia de cada pago al backend', async () => {
    vi.mocked(postOnboarding).mockResolvedValue({
      registroId: 'r1',
      total: 100,
      pagado: 100,
      estado: 'A',
      codigoAccesoPadres: 'c',
    })
    const store = prepararRegistroListo()

    await store.proceedToRFID([{ metodoPagoId: 'm-tarjeta', monto: 100, referencia: 'A-123' }])
    await store.completeRegistration()

    const payload = vi.mocked(postOnboarding).mock.calls[0][0]
    expect(payload.pagos).toEqual([{ metodoPagoId: 'm-tarjeta', monto: 100, referencia: 'A-123' }])
  })

  it('muestra el mensaje del backend cuando falta la referencia (422)', async () => {
    vi.mocked(postOnboarding).mockRejectedValue({
      statusCode: 422,
      message: 'El pago con «Tarjeta» requiere la referencia o el folio de autorización.',
    })
    const store = prepararRegistroListo()

    await store.proceedToRFID([{ metodoPagoId: 'm-tarjeta', monto: 100 }])
    await store.completeRegistration()

    expect(store.submitError).toContain('requiere la referencia')
  })
})

describe('registration store: aviso de privacidad (LFPDPPP)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(postOnboarding).mockReset()
    vi.mocked(postOnboarding).mockResolvedValue({
      registroId: 'r1',
      total: 100,
      pagado: 100,
      estado: 'A',
      codigoAccesoPadres: 'c',
    })
    vi.mocked(privacidadService.obtenerVigente).mockReset().mockResolvedValue(AVISO)
  })

  it('sin aceptar el aviso no deja continuar y dice por qué', () => {
    const store = prepararRegistroListo({ aceptaAviso: false })

    expect(store.canProceedToRFID).toBe(false)
    expect(store.motivosPendientes).toContain('El tutor debe leer y aceptar el aviso de privacidad')

    store.aceptaAvisoPrivacidad = true
    expect(store.canProceedToRFID).toBe(true)
    expect(store.motivosPendientes).toEqual([])
  })

  it('si el aviso no cargó, marcar la casilla no basta', () => {
    const store = prepararRegistroListo()
    store.avisoPrivacidad = null

    expect(store.avisoAceptado).toBe(false)
    expect(store.canProceedToRFID).toBe(false)
  })

  it('sin aceptación no envía nada al backend', async () => {
    const store = prepararRegistroListo({ aceptaAviso: false })

    await store.proceedToRFID([{ metodoPagoId: 'm-1', monto: 100 }])
    await store.completeRegistration()

    expect(postOnboarding).not.toHaveBeenCalled()
    expect(store.submitError).toContain('aviso de privacidad')
  })

  it('envía la versión aceptada y las finalidades voluntarias', async () => {
    const store = prepararRegistroListo()

    await store.proceedToRFID([{ metodoPagoId: 'm-1', monto: 100 }])
    await store.completeRegistration()

    const payload = vi.mocked(postOnboarding).mock.calls[0][0]
    expect(payload).toMatchObject({
      aceptaAvisoPrivacidad: true,
      versionAvisoPrivacidad: 4,
      aceptaFinalidadesSecundarias: true,
    })
  })

  it('si el tutor se niega a lealtad y promociones lo manda así', async () => {
    const store = prepararRegistroListo()
    store.rechazaFinalidadesSecundarias = true

    await store.proceedToRFID([{ metodoPagoId: 'm-1', monto: 100 }])
    await store.completeRegistration()

    expect(vi.mocked(postOnboarding).mock.calls[0][0].aceptaFinalidadesSecundarias).toBe(false)
  })

  it('si se publicó otra versión, recarga el aviso y pide aceptarlo de nuevo', async () => {
    const store = prepararRegistroListo()
    vi.mocked(postOnboarding).mockRejectedValue({
      statusCode: 422,
      code: 'AVISO_PRIVACIDAD_DESACTUALIZADO',
      message: 'El aviso de privacidad cambió mientras se capturaba el registro.',
    })
    vi.mocked(privacidadService.obtenerVigente).mockResolvedValue({ ...AVISO, version: 5 })

    await store.proceedToRFID([{ metodoPagoId: 'm-1', monto: 100 }])
    await store.completeRegistration()
    await Promise.resolve()

    expect(store.submitError).toContain('El aviso de privacidad cambió')
    expect(store.aceptaAvisoPrivacidad).toBe(false)
    expect(privacidadService.obtenerVigente).toHaveBeenCalledTimes(1)
    expect(store.avisoPrivacidad?.version).toBe(5)
    expect(store.step).toBe('rfid')
  })

  it('reset limpia la aceptación del tutor anterior', () => {
    const store = prepararRegistroListo()
    store.rechazaFinalidadesSecundarias = true

    store.reset()

    expect(store.aceptaAvisoPrivacidad).toBe(false)
    expect(store.rechazaFinalidadesSecundarias).toBe(false)
  })

  it('si no puede cargar el aviso lo avisa', async () => {
    vi.mocked(privacidadService.obtenerVigente).mockRejectedValue(new Error('red'))
    const store = useRegistrationStore()

    await store.cargarAvisoPrivacidad()

    expect(store.avisoPrivacidad).toBeNull()
    expect(store.errorAviso).toContain('No se pudo cargar el aviso de privacidad')
  })
})
