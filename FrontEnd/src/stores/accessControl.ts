import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchActivos,
  fetchPulseras,
  type ActivoDto,
  type PulseraDto,
} from '@/api/onboardingClient'
import { useAuthStore } from '@/stores/auth'

export type StayStatus = 'activo' | 'por_expirar' | 'excedido'

export interface ActiveChild extends ActivoDto {
  status: StayStatus
  minutosRestantes: number // positive = remaining, negative = exceeded
  progressPercent: number // 0-100, capped at 100
}

const EXPIRING_THRESHOLD_MINUTES = 15
// Antigüedad máxima de la lista de pulseras para reutilizarla sin pedirla otra vez.
const PULSERAS_MAX_EDAD_MS = 60_000

export const useAccessControlStore = defineStore('accessControl', () => {
  const authStore = useAuthStore()
  const rawActivos = ref<ActivoDto[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const lastUpdated = ref<Date | null>(null)
  const now = ref(Date.now())

  let tickTimer: ReturnType<typeof setInterval> | null = null

  function startTicking() {
    stopTicking()
    tickTimer = setInterval(() => {
      now.value = Date.now()
    }, 60_000)
  }

  function stopTicking() {
    if (tickTimer) {
      clearInterval(tickTimer)
      tickTimer = null
    }
  }

  const checkoutChild = ref<ActiveChild | null>(null)

  function setCheckoutChild(child: ActiveChild) {
    checkoutChild.value = child
  }

  function clearCheckoutChild() {
    checkoutChild.value = null
  }

  function computeStatus(item: ActivoDto): ActiveChild {
    const elapsedMs = lastUpdated.value ? now.value - lastUpdated.value.getTime() : 0
    const elapsedMinutes = Math.max(0, Math.floor(elapsedMs / 60_000))
    const minutosTranscurridos = item.minutosTranscurridos + elapsedMinutes

    const minutosRestantes = item.minutosPagados - minutosTranscurridos
    const progressPercent =
      item.minutosPagados > 0
        ? Math.min(100, Math.max(0, Math.round((minutosTranscurridos / item.minutosPagados) * 100)))
        : 100

    let status: StayStatus = 'activo'
    if (minutosRestantes < 0) {
      status = 'excedido'
    } else if (minutosRestantes <= EXPIRING_THRESHOLD_MINUTES) {
      status = 'por_expirar'
    }

    return { ...item, minutosTranscurridos, status, minutosRestantes, progressPercent }
  }

  const activos = computed<ActiveChild[]>(() => rawActivos.value.map(computeStatus))

  const totalActivos = computed(() => activos.value.filter((a) => a.status === 'activo').length)

  const porExpirar = computed(() => activos.value.filter((a) => a.status === 'por_expirar').length)

  const excedidos = computed(() => activos.value.filter((a) => a.status === 'excedido').length)

  const pulserasDisponibles = ref<PulseraDto[]>([])
  const pulserasLibres = computed(() => pulserasDisponibles.value.length)
  const puedeVerPulseras = computed(() => authStore.hasPermission('pulseras:listar'))

  async function loadActivos() {
    if (!authStore.currentBranchId) {
      error.value = 'No hay una sucursal activa en la sesión.'
      return
    }
    isLoading.value = true
    error.value = null
    try {
      rawActivos.value = await fetchActivos(authStore.currentBranchId)
      lastUpdated.value = new Date()
    } catch (err) {
      error.value = 'No se pudo cargar la lista de niños activos.'
      console.error(err)
    } finally {
      isLoading.value = false
    }

    // Las pulseras alimentan el indicador de disponibilidad y el selector de
    // registro; requieren un permiso aparte (pulseras:listar) y no deben
    // bloquear la lista de activos.
    // Ambas ramas se capturan: el polling no debe producir rechazos sin manejar.
    const ok = await cargarPulseras()
    if (!ok && puedeVerPulseras.value) error.value ??= 'No se pudo cargar la lista de pulseras.'
  }

  // ── Pulseras libres (A14) ────────────────────────────────────────────────
  // El registro de entrada las necesita aunque se abra por URL o tras F5, sin
  // pasar antes por Control de Acceso o Inicio. `pulserasCargadas` dice si la
  // lista actual viene del servidor (y de qué sucursal), para no volver a
  // pedirla si otra pantalla la acaba de traer; las peticiones simultáneas se
  // comparten en vez de duplicarse.
  const pulserasCargadas = ref(false)
  let pulserasActualizadasEn = 0
  const isLoadingPulseras = ref(false)
  const errorPulseras = ref<string | null>(null)
  let pulserasSucursalId: string | null = null
  let pulserasEnCurso: Promise<boolean> | null = null

  async function ejecutarCargaPulseras(sucursalId: string): Promise<boolean> {
    try {
      const lista = await fetchPulseras(sucursalId)
      // Si mientras tanto cambió la sucursal, esta respuesta ya no aplica.
      if (pulserasSucursalId !== sucursalId) return false
      pulserasDisponibles.value = lista
      pulserasCargadas.value = true
      pulserasActualizadasEn = Date.now()
      return true
    } catch (err) {
      if (pulserasSucursalId === sucursalId) {
        errorPulseras.value = 'No se pudo cargar la lista de pulseras disponibles.'
      }
      console.error(err)
      return false
    }
  }

  /** Pide las pulseras libres al servidor. Nunca lanza: devuelve si lo logró. */
  function cargarPulseras(): Promise<boolean> {
    const sucursalId = authStore.currentBranchId
    if (!sucursalId) {
      errorPulseras.value = 'No hay una sucursal activa en la sesión.'
      return Promise.resolve(false)
    }
    if (pulserasEnCurso && pulserasSucursalId === sucursalId) return pulserasEnCurso

    isLoadingPulseras.value = true
    errorPulseras.value = null
    if (pulserasSucursalId !== sucursalId) {
      pulserasCargadas.value = false
      pulserasDisponibles.value = []
    }
    pulserasSucursalId = sucursalId
    const peticion: Promise<boolean> = ejecutarCargaPulseras(sucursalId).finally(() => {
      if (pulserasEnCurso === peticion) {
        pulserasEnCurso = null
        isLoadingPulseras.value = false
      }
    })
    pulserasEnCurso = peticion
    return peticion
  }

  /**
   * Garantiza que las pulseras de la sucursal actual estén cargadas: si otra
   * pantalla las trajo hace menos de `maxEdadMs` (o las está trayendo) no
   * repite la petición; si la lista es más vieja, la refresca.
   */
  function asegurarPulserasCargadas(maxEdadMs = PULSERAS_MAX_EDAD_MS): Promise<boolean> {
    const mismaSucursal = pulserasSucursalId === authStore.currentBranchId
    const reciente = Date.now() - pulserasActualizadasEn <= maxEdadMs
    if (pulserasCargadas.value && mismaSucursal && reciente && !pulserasEnCurso) {
      return Promise.resolve(true)
    }
    return cargarPulseras()
  }

  /** Quita de la lista local las pulseras que se acaban de asignar en un registro. */
  function descartarPulseras(ids: string[]) {
    pulserasDisponibles.value = pulserasDisponibles.value.filter((p) => !ids.includes(p.id))
  }

  function formatMinutosLabel(item: ActiveChild): string {
    const transcurridoH = Math.floor(item.minutosTranscurridos / 60)
    const transcurridoM = item.minutosTranscurridos % 60
    const pagadoH = Math.floor(item.minutosPagados / 60)

    const transcurridoStr =
      transcurridoH > 0 ? `${transcurridoH}h ${transcurridoM}m` : `${transcurridoM}m`
    const pagadoStr = pagadoH > 0 ? `${pagadoH}h` : `${item.minutosPagados}m`

    return `${transcurridoStr} / ${pagadoStr}`
  }

  function formatRemainingLabel(item: ActiveChild): string {
    if (item.status === 'excedido') {
      const exceededBy = Math.abs(item.minutosRestantes)
      const h = Math.floor(item.minutosPagados / 60)
      const hLabel = h > 0 ? `${h}h` : `${item.minutosPagados}m`
      return `+${exceededBy}m (${hLabel})`
    }
    return `< ${item.minutosRestantes} min`
  }

  return {
    rawActivos,
    activos,
    totalActivos,
    isLoading,
    error,
    lastUpdated,
    startTicking,
    stopTicking,
    checkoutChild,
    setCheckoutChild,
    clearCheckoutChild,
    porExpirar,
    excedidos,
    pulserasLibres,
    pulserasDisponibles,
    puedeVerPulseras,
    pulserasCargadas,
    isLoadingPulseras,
    errorPulseras,
    cargarPulseras,
    asegurarPulserasCargadas,
    descartarPulseras,
    loadActivos,
    formatMinutosLabel,
    formatRemainingLabel,
  }
})
