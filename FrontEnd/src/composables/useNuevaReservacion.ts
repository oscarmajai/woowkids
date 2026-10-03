import { useQuasar } from 'quasar'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useTurnoCajaStore } from '@/stores/turnoCaja'

/**
 * Navegación al asistente de nueva reservación.
 *
 * Confirmar una reservación exige registrar el anticipo, y ese cobro se registra
 * contra la apertura de caja de quien lo captura (el endpoint de pagos de
 * reservación depende de `apertura_operando_id`). Sin turno abierto el asistente
 * no puede terminar, así que el botón resuelve antes a dónde mandar al usuario.
 *
 * Vive en un composable porque la pantalla de Reservaciones y el Dashboard tienen
 * el mismo botón: cuando la lógica estaba duplicada, el mismo error existía en
 * los dos lados.
 */
export function useNuevaReservacion() {
  const router = useRouter()
  const $q = useQuasar()

  return function irANuevaReservacion(): void {
    const turno = useTurnoCajaStore()
    const auth = useAuthStore()

    if (turno.estaOperando) {
      void router.push({ name: 'eventos-reservaciones-crear' })
      return
    }

    // M10: quien puede abrir caja (Cajero, y también el Administrador de sucursal
    // desde la migración 073: abre y cierra su propio turno en /pos/cierre) va a
    // abrirla. Solo a un rol que no abre caja se le explica qué falta en vez de
    // navegarlo a una pantalla que no puede usar.
    if (!auth.hasPermission('turnos_caja:abrir')) {
      $q.notify({
        type: 'warning',
        message: 'Se necesita una caja abierta para registrar el anticipo.',
        caption: 'Tu rol no opera caja: pide a un cajero que abra su turno.',
        position: 'top-right',
        timeout: 6000,
      })
      return
    }

    $q.notify({
      type: 'warning',
      message: 'Abre tu caja para poder registrar el anticipo de la reservación.',
      position: 'top-right',
      timeout: 5000,
    })
    void router.push({ name: 'pos-cierre' })
  }
}
