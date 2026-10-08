import QRCode from 'qrcode'

/**
 * URL del portal de padres que va en el QR del comprobante. Lleva el código
 * opaco que emite el backend, nunca el registroId.
 */
export function urlPortalPadres(codigo: string, origen = window.location.origin): string {
  return `${origen}/padres/access?code=${encodeURIComponent(codigo)}`
}

/** QR (data URL) del portal de padres para imprimir en el comprobante. */
export function qrPortalPadres(codigo: string): Promise<string> {
  return QRCode.toDataURL(urlPortalPadres(codigo), {
    width: 100,
    margin: 1,
    errorCorrectionLevel: 'M',
  })
}

/** Hora corta (HH:MM) como la imprime el comprobante. */
export function horaComprobante(fecha: Date): string {
  return fecha.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' })
}
