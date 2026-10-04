import type { RouteLocationNormalized, Router } from 'vue-router'
import { Notify } from 'quasar'
import { useAuthStore } from '@/stores/auth'
import { useAccessControlStore } from '@/stores/accessControl'
import { useTurnoCajaStore } from '@/stores/turnoCaja'

/** Rutas de la caja que exigen una sucursal (AdministradorSistema debe elegirla). */
const RUTAS_CAJA = new Set(['pos-caja', 'pos-cierre'])

function avisar(message: string): void {
  Notify.create({ type: 'warning', message, position: 'top-right' })
}

/**
 * B21: al rebotar por falta de permiso se dice por qué, en vez de mandar a
 * Inicio en silencio.
 */
export function mensajeSinPermiso(to: Pick<RouteLocationNormalized, 'meta'>): string {
  const titulo = to.meta.title
  return titulo
    ? `No tienes permiso para abrir «${titulo}».`
    : 'No tienes permiso para abrir esa página.'
}

export const MENSAJE_SIN_TURNO_REGISTRO =
  'Se requiere un turno de caja abierto para registrar una entrada, y tu usuario no abre caja.'

export const MENSAJE_SISTEMA_SIN_SUCURSAL =
  'Elige una sucursal en el selector del menú lateral para usar la caja.'

export function setupRouterGuards(router: Router): void {
  router.beforeEach(async (to, from) => {
    const auth = useAuthStore()

    if (to.meta.requiresAuth && !auth.isAuthenticated) {
      const refreshed = await auth.tryRefresh()
      if (!refreshed) {
        // Una ruta inexistente no se guarda como destino tras el login.
        if (to.name === 'not-found') return { name: 'login' }
        return { name: 'login', query: { redirect: to.fullPath } }
      }
    }

    if (to.meta.publicOnly && auth.isAuthenticated) {
      return { name: 'home' }
    }

    // El administrador inicial (o quien entró con la contraseña de fábrica)
    // no puede usar nada más hasta cambiarla: el backend responde 403 a todo.
    if (
      auth.isAuthenticated &&
      auth.currentUser?.debeCambiarPassword &&
      to.name !== 'cambiar-password'
    ) {
      const redirect = to.meta.requiresAuth && to.name !== 'home' ? to.fullPath : undefined
      return { name: 'cambiar-password', query: redirect ? { redirect } : {} }
    }

    if (to.meta.permissions?.length && auth.currentUser) {
      const allowed = to.meta.permissions.some((p) => auth.hasPermission(p))
      if (!allowed) {
        avisar(mensajeSinPermiso(to))
        return { name: 'home' }
      }
    }

    if (to.meta.roles?.length && auth.currentUser) {
      if (!to.meta.roles.some((r) => auth.hasRole(r))) {
        avisar(mensajeSinPermiso(to))
        return { name: 'home' }
      }
    }

    // AdministradorSistema no tiene sucursal propia: sin elegir una en el
    // selector, la caja no tiene dónde abrirse.
    if (RUTAS_CAJA.has(String(to.name)) && auth.isSistema && !auth.currentBranchId) {
      avisar(MENSAJE_SISTEMA_SIN_SUCURSAL)
      return { name: 'home' }
    }

    // B4: sin permiso para consultar su turno la consulta solo daba un error; se
    // deja pasar igual que cuando la carga falla (la página resuelve qué mostrar).
    if (to.meta.requiresTurno && auth.hasPermission('turnos_caja:ver_activo')) {
      const turno = useTurnoCajaStore()
      // `asegurarTurnoCargado` nunca lanza: distingue "turno cargado" (resultado.ok)
      // de "no se pudo cargar" (red/5xx/403), que no debe expulsar a nadie (#13, #17).
      const resultado = await turno.asegurarTurnoCargado()
      if (resultado.ok && !turno.estaOperando) {
        if (auth.hasPermission('pos:acceder')) {
          return { name: 'pos-cierre' }
        }
        Notify.create({
          type: 'warning',
          message: 'Se requiere un turno de caja abierto para continuar.',
          position: 'top-right',
        })
        return false
      }
      // resultado.ok === false: la carga falló por red/5xx/403. Se deja pasar;
      // la página debe mostrar turno.error en vez de expulsar sin motivo.
    }

    // El Administrador de sucursal no vende en mostrador (pos-caja), pero sí abre y
    // cierra su propio turno en pos-cierre: lo necesita para cobrar reservaciones y
    // eventos (#13). AdministradorSistema puede ambas.
    const esAdminDeSucursal = auth.hasRole('Administrador') && !auth.hasRole('AdministradorSistema')
    if (esAdminDeSucursal && to.name === 'pos-caja') {
      return { name: 'pos-historial-arqueos' }
    }

    if (to.name === 'estancias-registro-infantes') {
      const accessControlStore = useAccessControlStore()
      // El Cajero no tiene el permiso "pulseras:listar" — nunca puede saber el
      // conteo real, así que este guard no aplica para él (quedaría en 0 para
      // siempre y lo bloquearía sin importar el inventario real). Solo se
      // exige el mínimo de 2 libres a roles que sí pueden verlo.
      // Si se entra por URL o tras F5 la lista aún no está cargada: se pide
      // aquí (A14) en vez de rebotar a Control de Acceso. Si la carga falla
      // se deja pasar y la página muestra el error con opción de reintentar.
      if (accessControlStore.puedeVerPulseras) {
        const cargadas = await accessControlStore.asegurarPulserasCargadas()
        if (cargadas && accessControlStore.pulserasLibres < 2) {
          return { name: 'estancias-control-acceso' }
        }
      }
    }

    if (to.name === 'estancias-checkout') {
      const accessControlStore = useAccessControlStore()
      if (!accessControlStore.checkoutChild) {
        return { name: 'estancias-control-acceso' }
      }
    }

    if (to.name === 'estancias-registro-infantes') {
      const turno = useTurnoCajaStore()
      if (!turno.estaOperando) {
        if (auth.hasPermission('pos:acceder')) return { name: 'pos-cierre' }
        // Sin pos:acceder no puede abrir caja: rebotarlo a Apertura y Cierre
        // terminaba en Inicio sin explicación (B21).
        avisar(MENSAJE_SIN_TURNO_REGISTRO)
        // Entrando por URL no hay pantalla de la cual no moverse.
        return from.matched.length ? false : { name: 'estancias-control-acceso' }
      }
    }
  })
}
