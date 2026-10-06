/** Niño tal como sale en el comprobante de entrada de estancias. */
export interface NinoComprobante {
  nombre: string
  edad: number | null
  /** Notas / alergias. */
  notas?: string | null
}

/**
 * Datos que pinta el ticket del comprobante de entrada (ComprobanteEstancia.vue),
 * tanto al terminar el registro como al reimprimirlo desde Control de Acceso.
 */
export interface DatosComprobanteEstancia {
  sucursal: string
  cajero: string
  fecha: Date
  tutor: string
  telefono?: string | null
  ninos: NinoComprobante[]
  /** Hora de salida ya formateada (la más tardía del registro). */
  salidaEstimada: string
  total: number
  /** QR del portal de padres en data URL; vacío mientras no hay código. */
  qrCodeUrl: string
  /** Marca el ticket como reimpresión. */
  reimpresion?: boolean
}
