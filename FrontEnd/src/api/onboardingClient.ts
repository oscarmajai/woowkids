import { apiClient } from '@/api/axiosClient'
import { metodosPagoApi } from '@/api/metodosPagoApi'
import JSZip from 'jszip'

const onboardingClient = apiClient

// Las fotos de INE/llegada se sirven en una ruta protegida por JWT, que un
// <img src="..."> no puede enviar. Se descargan con el cliente autenticado y
// se exponen como blob URL para usarlas en <img>.
async function fetchFotoIneBlobUrl(registroId: string) {
  const { data } = await onboardingClient.get(`/uploads/identificaciones/${registroId}.jpg`, {
    responseType: 'blob',
  })
  return URL.createObjectURL(data)
}

export function fetchFotoIneUrl(registroId: string): Promise<string> {
  return fetchFotoIneBlobUrl(registroId)
}

export async function fetchFotosLlegadaUrls(registroId: string): Promise<string[]> {
  const { data } = await onboardingClient.get<Blob>(`/uploads/registros/${registroId}/llegadas`, {
    responseType: 'blob',
  })

  const zip = await JSZip.loadAsync(data)
  const urls: string[] = []

  try {
    for (const filename of Object.keys(zip.files)) {
      const file = zip.files[filename]
      if (!file.dir && /\.(jpe?g|png|webp)$/i.test(filename)) {
        const blob = await file.async('blob')
        urls.push(URL.createObjectURL(blob))
      }
    }
  } catch (err) {
    urls.forEach((u) => URL.revokeObjectURL(u))
    throw err
  }

  return urls
}

export interface FotosUploadResponse {
  fotoIneUrl?: string
  fotoLlegadaUrl?: string
}

export interface PulseraDto {
  id: string
  pulseraRfid: string
}

export interface OnboardingDetalle {
  nino: {
    nombreCompleto: string
    edad: number
    notas: string | null
  }
  productoId: string
  cantidad: number
  pulseraId: string
}

export interface OnboardingPago {
  metodoPagoId: string
  monto: number
  // N8: folio del voucher o referencia de la transferencia. El backend la exige
  // (422 REFERENCIA_REQUERIDA) si el método de pago tiene `requiere_referencia`.
  referencia?: string
}

export interface OnboardingPayload {
  sucursalId: string
  tutor: {
    nombreCompleto: string
    telefono: string
  }
  nombreSegundoTutor: string | null
  parentesco: string
  detalles: OnboardingDetalle[]
  pagos: OnboardingPago[]
  cambio?: number
  reservacionId?: string | null
  puntosARedimir?: number
  // LFPDPPP: el tutor aceptó la versión vigente del aviso de privacidad. Sin
  // esto el backend responde 422 AVISO_PRIVACIDAD_NO_ACEPTADO.
  aceptaAvisoPrivacidad: boolean
  versionAvisoPrivacidad: number | null
  // false si el tutor se negó a las finalidades voluntarias (lealtad y
  // promociones): el registro no acumula ni canjea puntos.
  aceptaFinalidadesSecundarias: boolean
}

export interface OnboardingResponse {
  registroId: string
  total: number
  pagado: number
  estado: string
  advertenciaEfectivo?: string | null
  // Código opaco del QR del portal de padres (A17). Solo llega en esta
  // respuesta; caduca a las 24 h o al hacer checkout del último niño.
  codigoAccesoPadres: string
}

export interface ActivoDto {
  registroId: string
  nombreSegundoTutor: string | null
  detalleId: string
  nino: string
  notas: string | null
  edad: number
  tutor: string
  telefono: string
  parentesco: string
  pulsera: string
  minutosPagados: number
  minutosTranscurridos: number
  // Timestamp real de entrada (antes el front lo derivaba de minutosTranscurridos).
  horaEntrada: string
  // Excedente estimado en este momento, con la misma fórmula que cotizarCheckout.
  cargoExtra: number
}

export interface CheckoutResponse {
  detalleId: string
  registroId: string
  horasExtra: number
  totalExtra: number
  ninosRestantes: number
}

export interface CotizacionCheckoutResponse {
  detalleId: string
  horasExtra: number
  totalExtra: number
  cotizadoEn: string
}

//Llamadas a la api

// Método de pago por defecto para cobros de estancia (check-in y cargos extra
// de checkout), hasta que exista un selector de método de pago en la UI.
export async function fetchMetodoPagoPorDefecto(): Promise<string | null> {
  const metodos = await metodosPagoApi.listar()
  const activo = metodos.find((m) => m.activo)
  return activo?.id ?? null
}

// GET /pulseras/sucursal/{sucursalId}
export async function fetchPulseras(sucursalId: string): Promise<PulseraDto[]> {
  const { data } = await onboardingClient.get<PulseraDto[]>(`/pulseras/sucursal/${sucursalId}`)
  return data
}

export type EstadoPulsera = 'disponible' | 'usada' | 'inactiva'

export interface PulseraEstadoDto extends PulseraDto {
  activo: boolean
  usada: boolean
  estado: EstadoPulsera
}

// GET /pulseras/sucursal/{sucursalId}/buscar?rfid=… (B14). Responde 404 si la
// pulsera no existe en la sucursal; si existe, dice si está libre, usada o inactiva.
export async function fetchEstadoPulsera(
  sucursalId: string,
  rfid: string,
): Promise<PulseraEstadoDto> {
  const { data } = await onboardingClient.get<PulseraEstadoDto>(
    `/pulseras/sucursal/${sucursalId}/buscar`,
    { params: { rfid } },
  )
  return data
}

// POST /estancias
export async function postOnboarding(
  payload: OnboardingPayload,
  fotoIne: File | Blob,
  fotosLlegada: File[],
): Promise<OnboardingResponse> {
  const formData = new FormData()

  formData.append('fotoIne', fotoIne)
  fotosLlegada.forEach((foto) => {
    formData.append('fotosLlegada', foto)
  })

  formData.append('payload', JSON.stringify(payload))

  const { data } = await onboardingClient.post<OnboardingResponse>('/estancias', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })

  return data
}

// GET /estancias/activos/{sucursalId}
export async function fetchActivos(sucursalId: string): Promise<ActivoDto[]> {
  const { data } = await onboardingClient.get<ActivoDto[]>(`/estancias/activos/${sucursalId}`)
  return data
}

// GET /estancias/{detalleId}/checkout/cotizacion
// Solo lectura: no registra hora_salida ni cargo. Se llama al entrar a la
// pantalla de checkout y de nuevo justo antes de confirmar la salida, porque
// el monto puede cambiar entre una llamada y otra (el backend recalcula con
// la hora real al confirmar, y rechaza si lo pagado ya no alcanza).
export async function cotizarCheckout(detalleId: string): Promise<CotizacionCheckoutResponse> {
  const { data } = await onboardingClient.get(`/estancias/${detalleId}/checkout/cotizacion`)
  return data
}

// POST /estancias/{detalleId}/checkout
// Si hay cargo extra (> 0), 'pagos' debe cubrir exactamente el monto vigente
// en el momento de esta llamada (recalculado en el backend) o responde 409.
export async function checkout(
  detalleId: string,
  pagos: OnboardingPago[] = [],
): Promise<CheckoutResponse> {
  const { data } = await onboardingClient.post(`/estancias/${detalleId}/checkout`, {
    pagos,
  })

  return data
}

export interface NinoComprobanteDto {
  nombre: string
  edad: number
  notas: string | null
  pulsera: string
  horas: number
  salidaEsperada: string
}

export interface ComprobanteEstanciaDto {
  registroId: string
  // Código nuevo del portal de padres: el del comprobante anterior ya no vale.
  codigoAccesoPadres: string
  sucursal: string
  cajero: string | null
  tutor: string
  telefono: string
  entrada: string
  total: number
  ninos: NinoComprobanteDto[]
}

// POST /estancias/registros/{registroId}/comprobante (N5)
// Re-emite el código del QR del portal de padres (revoca el anterior) y
// devuelve los datos para reimprimir el comprobante. 409 si ya no hay niños
// dentro del registro.
export async function reimprimirComprobante(registroId: string): Promise<ComprobanteEstanciaDto> {
  const { data } = await onboardingClient.post<ComprobanteEstanciaDto>(
    `/estancias/registros/${registroId}/comprobante`,
  )
  return data
}

// POST /estancias/{registro_id}/pagos
// N9: el backend espera un objeto PagoEstanciaExtraRequest ({ pagos, cambio }),
// no la lista de pagos suelta (con la lista respondía 422).
export async function pagarExtra(
  registroId: string,
  sucursalId: string,
  pagos: OnboardingPago[],
  cambio = 0,
): Promise<void> {
  await onboardingClient.post(
    `/estancias/${registroId}/pagos`,
    { pagos, cambio },
    {
      params: {
        sucursal_id: sucursalId,
      },
    },
  )
}
