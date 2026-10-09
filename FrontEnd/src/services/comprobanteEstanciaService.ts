import { reimprimirComprobante, type ComprobanteEstanciaDto } from '@/api/onboardingClient'
import type { DatosComprobanteEstancia } from '@/types/comprobanteEstancia'
import { horaComprobante, qrPortalPadres } from '@/utils/portalPadres'

/** Arma lo que pinta el ticket a partir de la respuesta de reimpresión. */
export function datosDeReimpresion(
  dto: ComprobanteEstanciaDto,
  qrCodeUrl: string,
): DatosComprobanteEstancia {
  const salidas = dto.ninos.map((n) => new Date(n.salidaEsperada).getTime())
  return {
    sucursal: dto.sucursal,
    cajero: dto.cajero ?? '—',
    fecha: new Date(dto.entrada),
    tutor: dto.tutor,
    telefono: dto.telefono,
    ninos: dto.ninos.map((n) => ({ nombre: n.nombre, edad: n.edad, notas: n.notas })),
    // Igual que el comprobante original: la salida del último niño.
    salidaEstimada: salidas.length ? horaComprobante(new Date(Math.max(...salidas))) : '—',
    total: dto.total,
    qrCodeUrl,
    reimpresion: true,
  }
}

/**
 * Pide al backend un código nuevo del portal de padres para el registro
 * (el QR del comprobante anterior deja de valer) y arma el comprobante.
 */
export async function reimprimirComprobanteEstancia(
  registroId: string,
): Promise<DatosComprobanteEstancia> {
  const dto = await reimprimirComprobante(registroId)
  // Sin la lista de niños o sin código no hay comprobante que imprimir: se
  // avisa con un mensaje claro en vez de fallar al armar el ticket.
  if (!Array.isArray(dto?.ninos) || !dto.codigoAccesoPadres) {
    throw new Error('El servidor devolvió un comprobante incompleto. Intenta de nuevo.')
  }
  return datosDeReimpresion(dto, await qrPortalPadres(dto.codigoAccesoPadres))
}
