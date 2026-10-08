import { useQuasar } from 'quasar'
import AutorizacionAdminDialog from '@/components/historial/AutorizacionAdminDialog.vue'
import {
  cancelarComanda as cancelarComandaApi,
  devolverComanda as devolverComandaApi,
} from '@/services/comandaService'
import { turnoParaAutorizacion } from '@/utils/autorizacionAdmin'
import { mensajeDeError } from '@/utils/errorHandler'

/** Textos extra del diálogo del PIN (la cancelación usa los de por defecto). */
interface TextosAutorizacion {
  aviso?: string
  botonLabel?: string
}

const TEXTOS_DEVOLUCION: TextosAutorizacion = {
  aviso:
    'El dinero se devuelve desde tu turno de caja: baja el esperado de su método de pago en el ' +
    'arqueo. El producto ya se entregó, así que no regresa al inventario.',
  botonLabel: 'Autorizar devolución',
}

/**
 * Cancela una comanda, o devuelve el dinero de una ya entregada. Si el
 * backend responde que hace falta la autorización de un administrador, pide su
 * correo y PIN (validados contra /turnos-caja/validar-pin-admin para el turno
 * que indica el backend) y reintenta con el token. Cualquier otro error del
 * servidor se relanza para que la vista muestre su mensaje.
 */
export function useCancelarComanda() {
  const $q = useQuasar()

  function pedirTokenAdmin(
    turnoId: string,
    mensaje: string,
    textos?: TextosAutorizacion,
  ): Promise<string | null> {
    return new Promise((resolve) => {
      $q.dialog({
        component: AutorizacionAdminDialog,
        componentProps: { turnoId, mensaje, ...textos },
      })
        .onOk((token: string) => resolve(token))
        .onCancel(() => resolve(null))
    })
  }

  /** Ejecuta la operación; si pide autorización, pide el PIN y reintenta. */
  async function conAutorizacion(
    operacion: (tokenPinAdmin?: string) => Promise<void>,
    textos?: TextosAutorizacion,
  ): Promise<boolean> {
    try {
      await operacion()
      return true
    } catch (err) {
      const turnoId = turnoParaAutorizacion(err)
      if (!turnoId) throw err
      const token = await pedirTokenAdmin(turnoId, mensajeDeError(err, ''), textos)
      if (!token) return false
      await operacion(token)
      return true
    }
  }

  /** `true` si se canceló; `false` si el usuario desistió al pedir el PIN. */
  async function cancelarComanda(comandaId: string, motivo: string): Promise<boolean> {
    return conAutorizacion((token) =>
      token ? cancelarComandaApi(comandaId, motivo, token) : cancelarComandaApi(comandaId, motivo),
    )
  }

  /**
   * Devuelve el dinero de una orden entregada (sin regresar stock). Siempre
   * pide el PIN de un administrador. `true` si se devolvió; `false` si el
   * usuario desistió.
   */
  async function devolverComanda(comandaId: string, motivo: string): Promise<boolean> {
    return conAutorizacion(
      (token) => devolverComandaApi(comandaId, motivo, token),
      TEXTOS_DEVOLUCION,
    )
  }

  return { cancelarComanda, devolverComanda }
}
