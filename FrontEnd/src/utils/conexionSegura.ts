/**
 * La caja, el punto de venta y la cámara usan APIs del navegador
 * (crypto.randomUUID, getUserMedia) que solo existen en un contexto seguro:
 * HTTPS o localhost. Desde otra computadora por HTTP fallan, así que se avisa.
 */
export interface UbicacionMinima {
  protocol: string
  host: string
  hostname: string
  pathname: string
  search: string
}

export function conexionInsegura(contextoSeguro: boolean = window.isSecureContext): boolean {
  return !contextoSeguro
}

/** La misma página por HTTPS (puerto 443 del servidor). */
export function urlSegura(ubicacion: UbicacionMinima = window.location): string {
  return `https://${ubicacion.hostname}${ubicacion.pathname}${ubicacion.search}`
}

/** Página del servidor que explica cómo instalar el certificado. El aviso solo
 * sale por HTTP, así que se usa el mismo origen (con su puerto). */
export function urlInstalarCertificado(ubicacion: UbicacionMinima = window.location): string {
  return `${ubicacion.protocol}//${ubicacion.host}/instalar-certificado`
}
