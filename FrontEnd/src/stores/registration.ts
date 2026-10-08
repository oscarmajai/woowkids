import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchEstadoPulsera,
  postOnboarding,
  type OnboardingDetalle,
  type OnboardingPago,
} from '@/api/onboardingClient'
import { productosApi } from '@/api/productosApi'
import { useAuthStore } from '@/stores/auth'
import { useAccessControlStore } from '@/stores/accessControl'
import { reservacionesApi } from '@/api/reservacionesApi'
import { horasFacturables } from '@/utils/horario'
import { tramoParaHoras } from '@/utils/tramosEstancia'
import type { EventoDelDia } from '@/types/reservaciones'
import type { PrecioEstancia, TramoEstancia } from '@/types/producto'
import { redondear2, TOLERANCIA_MONTO } from '@/utils/dinero'
import { privacidadService } from '@/services/privacidadService'
import type { AvisoPrivacidad } from '@/types/privacidad'
import { nuevoId } from '@/utils/uuid'

export interface Child {
  id: string
  name: string
  age: number | null
  notes: string
  rfidBracelet: string
  saved: boolean
  // Tiempo de juego de este niño (independiente del de sus hermanos en el
  // mismo registro). En modo evento se ignora: todos usan horasEvento.
  estimatedTime: string
}

export interface TutorData {
  fullName: string
  relationship: string
  phone: string
  secondaryGuardian: string | null
  inePhoto: File | null
  arrivalPhotos: File[]
  estimatedTime: string
}

const HOUR_OPTIONS: Record<string, number> = {
  '1 hr': 1,
  '2 hr': 2,
  '3 hr': 3,
  '4 hr': 4,
  '5 hr': 5,
}

export type RegistrationStep = 'form' | 'rfid' | 'complete'

export type ResultadoPulsera = { ok: true; pulseraId: string } | { ok: false; mensaje: string }
export type RegistrationMode = 'normal' | 'evento'

export const useRegistrationStore = defineStore('registration', () => {
  const authStore = useAuthStore()
  const accessControlStore = useAccessControlStore()
  const step = ref<RegistrationStep>('form')

  const modo = ref<RegistrationMode>('normal')
  const eventoSeleccionado = ref<EventoDelDia | null>(null)
  const isLoadingEvento = ref(false)
  const eventoNoEncontrado = ref(false)

  const isEventoMode = computed(() => modo.value === 'evento')
  // Pasos de pulseras y listo: el formulario ya no se edita.
  const isLocked = computed(() => step.value === 'rfid' || step.value === 'complete')
  // En modo evento el nombre y el teléfono vienen de la reservación; las
  // fotos, el segundo tutor y los niños se siguen capturando.
  const datosTutorFijos = computed(() => isLocked.value || isEventoMode.value)

  const tutor = ref<TutorData>({
    fullName: '',
    relationship: 'Padre / Madre',
    phone: '',
    secondaryGuardian: '',
    inePhoto: null,
    arrivalPhotos: [],
    estimatedTime: '1 hr',
  })

  const children = ref<Child[]>([createChild()])
  const currentChildIndex = ref(0)

  const productoBase = ref<PrecioEstancia | null>(null)
  const pulseras = computed(() => accessControlStore.pulserasDisponibles)
  const isLoadingPulseras = computed(() => accessControlStore.isLoadingPulseras)
  const errorPulseras = computed(() => accessControlStore.errorPulseras)
  const pagosFromModal = ref<OnboardingPago[]>([])
  const cambioFromModal = ref(0)
  const puntosARedimirValue = ref(0)
  const descuentoPuntosValue = ref(0)
  const isLoadingCatalog = ref(false)
  const isSubmitting = ref(false)
  const submitError = ref<string | null>(null)
  const noPreciosDisponibles = ref(false)

  const registroId = ref('')
  // Código del QR del portal de padres: solo lo devuelve el backend al
  // crear el registro; no es el registroId.
  const codigoAccesoPadres = ref('')
  const totalFromServer = ref<number | null>(null)
  const pagadoFromServer = ref<number | null>(null)
  const estadoFromServer = ref('')
  const advertenciaEfectivoFromServer = ref<string | null>(null)

  // ── Aviso de privacidad (LFPDPPP) ─────────────────────────────────────────
  // El tutor debe aceptar la versión vigente antes de registrar la entrada
  // (la casilla viene marcada; el cajero la desmarca si el tutor no acepta);
  // las finalidades voluntarias (lealtad y promociones) se aceptan salvo que
  // se niegue (consentimiento tácito).
  const avisoPrivacidad = ref<AvisoPrivacidad | null>(null)
  const cargandoAviso = ref(false)
  const errorAviso = ref<string | null>(null)
  const aceptaAvisoPrivacidad = ref(true)
  const rechazaFinalidadesSecundarias = ref(false)
  const avisoAceptado = computed(
    () => aceptaAvisoPrivacidad.value && avisoPrivacidad.value !== null,
  )

  async function cargarAvisoPrivacidad() {
    cargandoAviso.value = true
    errorAviso.value = null
    try {
      avisoPrivacidad.value = await privacidadService.obtenerVigente()
    } catch (err) {
      errorAviso.value =
        'No se pudo cargar el aviso de privacidad; sin él no se puede registrar la entrada.'
      console.error(err)
    } finally {
      cargandoAviso.value = false
    }
  }

  function createChild(): Child {
    return {
      id: nuevoId(),
      name: '',
      age: null,
      notes: '',
      rfidBracelet: '',
      saved: false,
      // Arranca con el tiempo que tenga capturado el tutor en ese momento;
      // cada niño puede cambiarlo después sin afectar a los demás.
      estimatedTime: tutor.value.estimatedTime,
    }
  }

  function addChild() {
    children.value.push(createChild())
    currentChildIndex.value = children.value.length - 1
  }

  function removeChild(index: number) {
    if (children.value.length > 1) {
      children.value.splice(index, 1)
      if (currentChildIndex.value >= children.value.length) {
        currentChildIndex.value = children.value.length - 1
      }
    }
  }

  function saveChild(index: number) {
    children.value[index].saved = true
  }

  function editChild(index: number) {
    children.value[index].saved = false
  }

  async function loadProductos() {
    if (!authStore.currentBranchId) {
      submitError.value = 'No hay una sucursal activa en la sesión.'
      return
    }
    isLoadingCatalog.value = true
    submitError.value = null
    noPreciosDisponibles.value = false
    try {
      productoBase.value = await productosApi.obtenerPreciosEstancia()

      // Verificar si hay rangos de precios configurados
      if (!productoBase.value?.config_estancia?.length) {
        noPreciosDisponibles.value = true
      }
    } catch (err) {
      submitError.value = 'No se pudo cargar el catálogo de precios de estancia.'
      console.error(err)
    } finally {
      isLoadingCatalog.value = false
    }
  }

  // La página de registro carga por sí misma lo que necesita (tarifas y
  // pulseras libres de la sucursal), aunque se abra por URL o tras F5. Si
  // Control de Acceso acaba de traer las pulseras, no se vuelven a pedir.
  // El turno lo garantiza el guard de ruta (`requiresTurno`).
  async function cargarDatosIniciales() {
    if (!authStore.currentBranchId) {
      submitError.value = 'No hay una sucursal activa en la sesión.'
      return
    }
    await Promise.all([
      loadProductos(),
      accessControlStore.asegurarPulserasCargadas(),
      cargarAvisoPrivacidad(),
    ])
  }

  const isLoadingInicial = computed(() => isLoadingCatalog.value || isLoadingPulseras.value)

  async function cargarEventoProximo() {
    if (!authStore.currentBranchId) return
    isLoadingEvento.value = true
    eventoNoEncontrado.value = false
    try {
      const evento = await reservacionesApi.eventoProximo(authStore.currentBranchId)
      if (evento) {
        seleccionarEvento(evento)
      } else {
        eventoSeleccionado.value = null
        eventoNoEncontrado.value = true
      }
    } catch (err) {
      submitError.value = 'No se pudo consultar el evento próximo.'
      console.error(err)
    } finally {
      isLoadingEvento.value = false
    }
  }

  function cambiarModo(nuevoModo: RegistrationMode) {
    modo.value = nuevoModo
    eventoSeleccionado.value = null
    eventoNoEncontrado.value = false

    if (nuevoModo === 'evento') {
      void cargarEventoProximo()
    }
  }

  function seleccionarEvento(evento: EventoDelDia) {
    eventoSeleccionado.value = evento
    tutor.value.fullName = [evento.nombre_cliente, evento.apellidos_cliente]
      .filter(Boolean)
      .join(' ')
    tutor.value.phone = evento.telefono_cliente
  }

  const savedChildren = computed(() => children.value.filter((c) => c.saved))
  // Tiempo por defecto para niños nuevos (ver createChild); ya no determina
  // el precio total, que ahora se calcula por niño (ver hoursForChild).
  const hours = computed(() => HOUR_OPTIONS[tutor.value.estimatedTime] ?? 1)

  // ── Cálculo de tarifa por tramos, por niño ────────────────────────────────
  // Cada niño puede contratar un tiempo distinto; en modo evento
  // todos usan horasEvento (el tiempo lo define el evento, no el selector).

  // Misma regla que el backend (tramos ordenados; en un extremo compartido,
  // "0–1 h" y "1–2 h", gana el que termina ahí): ver utils/tramosEstancia.
  function tramoFor(horasSolicitadas: number): TramoEstancia | null {
    return tramoParaHoras(productoBase.value?.config_estancia ?? [], horasSolicitadas)
  }

  const tieneTarifaValida = computed(() => {
    if (modo.value === 'evento') return true
    return (productoBase.value?.config_estancia?.length ?? 0) > 0
  })

  function hoursForChild(child: Child): number {
    if (modo.value === 'evento') return HOUR_OPTIONS[horasEvento.value] ?? 1
    return HOUR_OPTIONS[child.estimatedTime] ?? 1
  }

  function priceForChild(child: Child): number {
    if (modo.value === 'evento') return 0
    const horasChild = hoursForChild(child)
    const tramo = tramoFor(horasChild)
    if (!tramo) return 0
    return Number(tramo.precio) * horasChild
  }

  const total = computed(() =>
    savedChildren.value.reduce((suma, child) => suma + priceForChild(child), 0),
  )

  const usedBracelets = computed(() => children.value.map((c) => c.rfidBracelet).filter(Boolean))

  const availableBraceletsForChild = (childId: string) => {
    const child = children.value.find((c) => c.id === childId)
    return pulseras.value.filter(
      (p) => !usedBracelets.value.includes(p.id) || p.id === child?.rfidBracelet,
    )
  }

  function pulseraAsignadaAOtroNino(childId: string, pulseraId: string): boolean {
    return savedChildren.value.some((c) => c.id !== childId && c.rfidBracelet === pulseraId)
  }

  /**
   * Valida una pulsera escaneada para un niño. Si no está entre las
   * libres que tiene la página, se consulta al servidor para distinguir una
   * pulsera inexistente de una ya asignada a otro niño o desactivada.
   */
  async function validarPulseraEscaneada(
    childId: string,
    rfidEscaneado: string,
  ): Promise<ResultadoPulsera> {
    const rfid = rfidEscaneado.trim()
    const local = pulseras.value.find((p) => p.pulseraRfid === rfid)
    if (local) {
      if (pulseraAsignadaAOtroNino(childId, local.id)) {
        return {
          ok: false,
          mensaje: `La pulsera "${rfid}" ya está asignada a otro niño de este registro.`,
        }
      }
      return { ok: true, pulseraId: local.id }
    }

    if (!authStore.currentBranchId) {
      return { ok: false, mensaje: 'No hay una sucursal activa en la sesión.' }
    }

    try {
      const pulsera = await fetchEstadoPulsera(authStore.currentBranchId, rfid)
      if (pulsera.estado === 'usada') {
        return { ok: false, mensaje: `La pulsera "${rfid}" ya está asignada a otro niño.` }
      }
      if (pulsera.estado === 'inactiva') {
        return { ok: false, mensaje: `La pulsera "${rfid}" está desactivada.` }
      }
      // Libre en el servidor pero no en la lista local (se dio de alta después
      // de cargarla): se incorpora para poder mostrarla y asignarla.
      if (!pulseras.value.some((p) => p.id === pulsera.id)) {
        accessControlStore.pulserasDisponibles.push({
          id: pulsera.id,
          pulseraRfid: pulsera.pulseraRfid,
        })
      }
      if (pulseraAsignadaAOtroNino(childId, pulsera.id)) {
        return {
          ok: false,
          mensaje: `La pulsera "${rfid}" ya está asignada a otro niño de este registro.`,
        }
      }
      return { ok: true, pulseraId: pulsera.id }
    } catch (err: unknown) {
      if ((err as { statusCode?: number } | null)?.statusCode === 404) {
        return { ok: false, mensaje: `La pulsera "${rfid}" no existe en esta sucursal.` }
      }
      console.error(err)
      return { ok: false, mensaje: `No se pudo verificar la pulsera "${rfid}". Intenta de nuevo.` }
    }
  }

  // Código impreso de cada pulsera asignada (WK-0000001). Al terminar el
  // registro la pulsera sale de las disponibles y ya no se encontraría ahí:
  // el resumen mostraba su id interno.
  const etiquetasPulsera = ref<Record<string, string>>({})

  /** Valida y, si procede, asigna la pulsera escaneada al niño. */
  async function asignarPulseraEscaneada(
    childId: string,
    rfidEscaneado: string,
  ): Promise<ResultadoPulsera> {
    const resultado = await validarPulseraEscaneada(childId, rfidEscaneado)
    if (resultado.ok) {
      const child = children.value.find((c) => c.id === childId)
      if (child) child.rfidBracelet = resultado.pulseraId
      etiquetasPulsera.value[resultado.pulseraId] = rfidEscaneado.trim()
    }
    return resultado
  }

  /** Código de la pulsera para mostrarlo (su id interno solo si no se conoce). */
  function etiquetaPulsera(pulseraId: string): string {
    return (
      etiquetasPulsera.value[pulseraId] ??
      pulseras.value.find((p) => p.id === pulseraId)?.pulseraRfid ??
      pulseraId
    )
  }

  const allChildrenHaveBracelet = computed(
    () => savedChildren.value.length > 0 && savedChildren.value.every((c) => c.rfidBracelet !== ''),
  )

  const cupoEventoRestante = computed(() => {
    if (!eventoSeleccionado.value) return Infinity
    return eventoSeleccionado.value.numero_personas - savedChildren.value.length
  })

  // Regla: horas facturables (hora iniciada cuenta completa, cruza medianoche),
  // acotadas al rango del selector de tiempo (1 a 5 hr).
  const horasEvento = computed(() => {
    if (!eventoSeleccionado.value) return '1 hr'
    const horas = horasFacturables(
      eventoSeleccionado.value.hora_inicio,
      eventoSeleccionado.value.hora_fin,
    )
    return `${Math.min(5, horas)} hr`
  })

  const maxChildrenAllowed = computed(() => {
    if (modo.value === 'evento' && eventoSeleccionado.value) {
      return eventoSeleccionado.value.numero_personas
    }
    return Math.max(0, pulseras.value.length - 1)
  })

  const reachedBraceletLimit = computed(
    () => savedChildren.value.length >= maxChildrenAllowed.value,
  )

  const showBraceletLimitBanner = computed(() => {
    if (modo.value === 'evento') {
      return savedChildren.value.length >= maxChildrenAllowed.value
    }
    if (maxChildrenAllowed.value === 1) {
      return true
    }
    return savedChildren.value.length >= 2 && savedChildren.value.length >= maxChildrenAllowed.value
  })

  const canProceedToRFID = computed(() => {
    const hasValidName = tutor.value.fullName.trim().length > 3

    const cleanPhone = tutor.value.phone.replace(/\D/g, '')
    const hasValidPhone = cleanPhone.length === 10

    const hasInePhoto = tutor.value.inePhoto !== null
    const hasArrivalPhotos = tutor.value.arrivalPhotos.length > 0

    const hasChildren = savedChildren.value.length > 0

    const childrenAreValid = savedChildren.value.every(
      (child) =>
        child.name.trim().length > 0 && child.age !== null && child.age > 0 && child.age < 18,
    )

    return (
      hasValidName &&
      hasValidPhone &&
      hasInePhoto &&
      hasArrivalPhotos &&
      hasChildren &&
      childrenAreValid &&
      tieneTarifaValida.value &&
      avisoAceptado.value
    )
  })

  const motivosPendientes = computed(() => {
    const motivos: string[] = []

    if (tutor.value.fullName.trim().length <= 3) {
      motivos.push('Captura el nombre completo del tutor')
    }
    if (tutor.value.phone.replace(/\D/g, '').length !== 10) {
      motivos.push('El teléfono del tutor debe tener 10 dígitos')
    }
    if (tutor.value.inePhoto === null) {
      motivos.push('Toma la foto de INE del tutor')
    }
    if (tutor.value.arrivalPhotos.length === 0) {
      motivos.push('Toma al menos una foto de llegada del tutor')
    }
    if (savedChildren.value.length === 0) {
      motivos.push('Guarda al menos un niño')
    } else if (
      !savedChildren.value.every(
        (child) =>
          child.name.trim().length > 0 && child.age !== null && child.age > 0 && child.age < 18,
      )
    ) {
      motivos.push('Revisa el nombre y la edad de cada niño guardado')
    }

    if (!tieneTarifaValida.value) {
      motivos.push('No hay tarifas de estancia configuradas.')
    }
    if (!avisoAceptado.value) {
      motivos.push('El tutor debe leer y aceptar el aviso de privacidad')
    }

    return motivos
  })

  async function proceedToRFID(
    pagos?: OnboardingPago[],
    cambio?: number,
    puntosARedimir?: number,
    descuentoPuntos?: number,
  ) {
    if (pagos) {
      pagosFromModal.value = pagos
      cambioFromModal.value = cambio ?? 0
    }
    if (puntosARedimir) {
      puntosARedimirValue.value = puntosARedimir
    }
    if (descuentoPuntos) {
      descuentoPuntosValue.value = descuentoPuntos
    }
    step.value = 'rfid'
  }

  async function completeRegistration() {
    const esEvento = modo.value === 'evento'

    if (!productoBase.value) {
      submitError.value =
        'Esta sucursal no tiene un producto de tipo "estancia" configurado. ' +
        'Ve a Catálogo > Productos y crea uno antes de completar el registro.'
      return
    }

    if (!tieneTarifaValida.value) {
      submitError.value = 'No hay un precio de estancia configurado para esta sucursal.'
      return
    }

    if (esEvento && !eventoSeleccionado.value) {
      submitError.value = 'Selecciona el evento antes de completar el registro.'
      return
    }

    if (!authStore.currentBranchId) {
      submitError.value = 'No hay una sucursal activa en la sesión.'
      return
    }

    if (!avisoAceptado.value) {
      submitError.value = 'El tutor debe leer y aceptar el aviso de privacidad.'
      return
    }

    if (!esEvento) {
      // Los pagos (puede venir vacío si los puntos cubren todo) más el
      // descuento por puntos deben cuadrar exactamente con el total: si no,
      // no se envía nada al backend (evita cobros fantasma o dobles).
      // En efectivo el monto es lo entregado; el cambio se descuenta para cuadrar.
      const sumaPagos =
        pagosFromModal.value.reduce((acc, p) => acc + p.monto, 0) - cambioFromModal.value
      const cuadra =
        Math.abs(redondear2(sumaPagos + descuentoPuntosValue.value) - redondear2(total.value)) <=
        TOLERANCIA_MONTO
      if (!cuadra) {
        submitError.value = 'Los pagos capturados no cubren el total del registro. Vuelve a cobrar.'
        return
      }
    }

    isSubmitting.value = true
    submitError.value = null

    const detalles: OnboardingDetalle[] = savedChildren.value.map((child) => ({
      nino: { nombreCompleto: child.name, edad: child.age ?? 0, notas: child.notes },
      productoId: productoBase.value!.id,
      cantidad: hoursForChild(child),
      pulseraId: child.rfidBracelet,
    }))

    const payload = {
      sucursalId: authStore.currentBranchId,
      tutor: {
        nombreCompleto: tutor.value.fullName,
        telefono: tutor.value.phone,
      },
      nombreSegundoTutor: tutor.value.secondaryGuardian || null,
      parentesco: tutor.value.relationship,
      detalles,
      pagos: esEvento ? [] : pagosFromModal.value,
      cambio: cambioFromModal.value > 0 ? cambioFromModal.value : undefined,
      reservacionId: esEvento ? eventoSeleccionado.value!.id : null,
      puntosARedimir: puntosARedimirValue.value,
      aceptaAvisoPrivacidad: aceptaAvisoPrivacidad.value,
      versionAvisoPrivacidad: avisoPrivacidad.value?.version ?? null,
      aceptaFinalidadesSecundarias: !rechazaFinalidadesSecundarias.value,
    }

    try {
      const response = await postOnboarding(
        payload,
        tutor.value.inePhoto!,
        tutor.value.arrivalPhotos,
      )

      registroId.value = response.registroId
      codigoAccesoPadres.value = response.codigoAccesoPadres
      totalFromServer.value = response.total
      pagadoFromServer.value = response.pagado
      estadoFromServer.value = response.estado
      advertenciaEfectivoFromServer.value = response.advertenciaEfectivo ?? null
      // Las pulseras recién asignadas ya no están libres: el siguiente registro
      // no debe ofrecerlas aunque reutilice la lista ya cargada.
      accessControlStore.descartarPulseras(detalles.map((d) => d.pulseraId))
      step.value = 'complete'
    } catch (err: any) {
      if (err?.statusCode === 409) {
        const message = err?.message || ''
        if (message.includes('pulsera no puede asignarse a más de un niño en el mismo registro')) {
          submitError.value =
            'No puedes asignar la misma pulsera a más de un niño. Verifica las pulseras asignadas.'
        } else if (message.includes('ya fue usada o no está disponible')) {
          submitError.value = 'Una de las pulseras seleccionadas ya fue usada o no está disponible.'
        } else {
          submitError.value = message || 'No se pudo completar el registro. Intenta de nuevo.'
        }
      } else if (err?.statusCode === 422 && err?.code === 'AVISO_PRIVACIDAD_DESACTUALIZADO') {
        // Se publicó otra versión mientras se capturaba: se carga la nueva y
        // el tutor debe aceptarla otra vez.
        aceptaAvisoPrivacidad.value = false
        void cargarAvisoPrivacidad()
        submitError.value = err.message
      } else if (err?.statusCode === 422 && err?.message) {
        // P. ej. un pago con tarjeta o transferencia sin referencia.
        submitError.value = err.message
      } else {
        submitError.value = 'No se pudo completar el registro. Intenta de nuevo.'
      }
      console.error(err)
    } finally {
      isSubmitting.value = false
    }
  }

  function reset() {
    step.value = 'form'
    codigoAccesoPadres.value = ''
    modo.value = 'normal'
    eventoSeleccionado.value = null
    eventoNoEncontrado.value = false
    pagosFromModal.value = []
    cambioFromModal.value = 0
    puntosARedimirValue.value = 0
    descuentoPuntosValue.value = 0
    aceptaAvisoPrivacidad.value = true
    rechazaFinalidadesSecundarias.value = false
    tutor.value = {
      fullName: '',
      relationship: 'Padre / Madre',
      phone: '',
      secondaryGuardian: '',
      inePhoto: null,
      arrivalPhotos: [],
      estimatedTime: '1 hr',
    }
    children.value = [createChild()]
    currentChildIndex.value = 0
  }

  return {
    step,
    modo,
    isEventoMode,
    isLocked,
    datosTutorFijos,
    eventoSeleccionado,
    isLoadingEvento,
    eventoNoEncontrado,
    cupoEventoRestante,
    horasEvento,
    tutor,
    children,
    currentChildIndex,
    productoBase,
    pulseras,
    isLoadingPulseras,
    errorPulseras,
    isLoadingInicial,
    isLoadingCatalog,
    isSubmitting,
    submitError,
    noPreciosDisponibles,
    registroId,
    codigoAccesoPadres,
    totalFromServer,
    pagadoFromServer,
    estadoFromServer,
    pagosFromModal,
    advertenciaEfectivoFromServer,
    avisoPrivacidad,
    cargandoAviso,
    errorAviso,
    aceptaAvisoPrivacidad,
    rechazaFinalidadesSecundarias,
    avisoAceptado,
    cargarAvisoPrivacidad,
    savedChildren,
    hours,
    tieneTarifaValida,
    hoursForChild,
    priceForChild,
    total,
    usedBracelets,
    availableBraceletsForChild,
    allChildrenHaveBracelet,
    canProceedToRFID,
    motivosPendientes,
    maxChildrenAllowed,
    reachedBraceletLimit,
    showBraceletLimitBanner,
    addChild,
    removeChild,
    saveChild,
    editChild,
    proceedToRFID,
    completeRegistration,
    reset,
    loadProductos,
    cargarDatosIniciales,
    validarPulseraEscaneada,
    asignarPulseraEscaneada,
    etiquetaPulsera,
    cargarEventoProximo,
    cambiarModo,
    seleccionarEvento,
  }
})
