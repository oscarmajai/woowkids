import { useQuasar } from 'quasar'
import AutorizacionAdminDialog from '@/components/historial/AutorizacionAdminDialog.vue'
import { cancelarComanda as cancelarComandaApi } from '@/services/comandaService'
import { turnoParaAutorizacion } from '@/utils/autorizacionAdmin'
import { mensajeDeError } from '@/utils/errorHandler'

/**
 * A4: cancela una comanda. Si el backend responde que está pagada y necesita
 * la autorización de un administrador, pide su correo y PIN (validados contra
 * /turnos-caja/validar-pin-admin para el turno que indica el backend) y
 * reintenta con el token. Cualquier otro error del servidor se relanza para
 * que la vista muestre su mensaje.
 */
export function useCancelarComanda() {
  const $q = useQuasar()

  function pedirTokenAdmin(turnoId: string, mensaje: string): Promise<string | null> {
    return new Promise((resolve) => {
      $q.dialog({
        component: AutorizacionAdminDialog,
        componentProps: { turnoId, mensaje },
      })
        .onOk((token: string) => resolve(token))
        .onCancel(() => resolve(null))
    })
  }

  /** `true` si se canceló; `false` si el usuario desistió al pedir el PIN. */
  async function cancelarComanda(comandaId: string, motivo: string): Promise<boolean> {
    try {
      await cancelarComandaApi(comandaId, motivo)
      return true
    } catch (err) {
      const turnoId = turnoParaAutorizacion(err)
      if (!turnoId) throw err
      const token = await pedirTokenAdmin(turnoId, mensajeDeError(err, ''))
      if (!token) return false
      await cancelarComandaApi(comandaId, motivo, token)
      return true
    }
  }

  return { cancelarComanda }
}
