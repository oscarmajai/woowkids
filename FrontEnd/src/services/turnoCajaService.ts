import { turnoCajaApi } from '@/api/turnoCajaApi'
import { resolveErrorMessage } from '@/utils/errorHandler'
import { downloadBlob } from '@/utils/downloadBlob'
import type { ApiError } from '@/types/auth'
import type {
  PropositoPinAdmin,
  ResultadoValidacionPin,
  TurnoActivoResponse,
  AbrirTurnoPayload,
  ConteoPayload,
  RevisionAdminPayload,
  RevisionAdminResponse,
  ConfirmarCierrePayload,
  ConfirmarCierreResponse,
  FiltrosHistorial,
  HistorialArqueosResponse,
  ResumenHistorialArqueos,
  DetalleArqueo,
  IngresoEfectivoPayload,
  IngresoEfectivoResponse,
  RetiroParcialPayload,
  RetiroParcialResponse,
} from '@/types/turnoCaja'

// ─────────────────────────────────────────────────────────────────────────────
// Errores de dominio — el store los captura y muestra al usuario
// ─────────────────────────────────────────────────────────────────────────────

export class TurnoNoEncontradoError extends Error {
  constructor() {
    super('No se encontró un turno activo para esta sesión.')
    this.name = 'TurnoNoEncontradoError'
  }
}

export class TransicionInvalidaError extends Error {
  constructor(mensaje: string) {
    super(mensaje)
    this.name = 'TransicionInvalidaError'
  }
}

export class CredencialesAdminInvalidasError extends Error {
  /**
   * A16: el backend explica qué falló (p. ej. que el administrador ya tiene PIN
   * y no se acepta su contraseña); sin mensaje se usa el genérico.
   */
  constructor(mensaje?: string) {
    super(mensaje || 'Credenciales de administrador incorrectas. Verifica el correo y el PIN.')
    this.name = 'CredencialesAdminInvalidasError'
  }
}

// A5: el backend responde 403 con estos códigos cuando el PIN/contraseña de
// caja no coincide (antes 401, que el interceptor confundía con sesión vencida).
const CODIGOS_CREDENCIAL_INVALIDA = new Set(['CREDENCIALES_INVALIDAS', 'PIN_INVALIDO'])

// ─────────────────────────────────────────────────────────────────────────────
// Helper interno — convierte cualquier error a mensaje de usuario
// ─────────────────────────────────────────────────────────────────────────────

function toMensajeError(err: unknown): string {
  // Errores de dominio propios: mensaje ya es legible
  if (err instanceof Error && err.name !== 'Error') return err.message

  // Errores HTTP del axiosClient
  return resolveErrorMessage(err as ApiError)
}

// ─────────────────────────────────────────────────────────────────────────────
// Servicio — objeto literal (patrón del proyecto)
// ─────────────────────────────────────────────────────────────────────────────

export const turnoCajaService = {
  /**
   * Obtiene la lista de turnos configurados en la BD mediante petición al backend.
   */
  async obtenerTurnos() {
    return await turnoCajaApi.obtenerTurnos()
  },

  /**
   * Obtiene la lista de cajas de la sucursal activa mediante petición al backend.
   */
  async obtenerCajas(sucursalId?: string | null) {
    return await turnoCajaApi.obtenerCajas(sucursalId)
  },

  /**
   * Registra un retiro parcial sobre el turno activo (solo en estado OPERANDO).
   */
  async registrarRetiro(payload: RetiroParcialPayload): Promise<RetiroParcialResponse> {
    try {
      return await turnoCajaApi.registrarRetiro(payload)
    } catch (err) {
      const apiErr = err as ApiError
      // B17: el 409 puede ser "excede el efectivo disponible (disponible: $X)"
      // o "el turno está en conteo": se muestra lo que dice el backend.
      if (apiErr.statusCode === 409)
        throw new TransicionInvalidaError(
          apiErr.message || 'No se pueden registrar retiros en este momento.',
        )
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Registra un ingreso de efectivo sobre el turno activo (solo en estado OPERANDO).
   */
  async registrarIngreso(payload: IngresoEfectivoPayload): Promise<IngresoEfectivoResponse> {
    try {
      return await turnoCajaApi.registrarIngreso(payload)
    } catch (err) {
      const apiErr = err as ApiError
      if (apiErr.statusCode === 409)
        throw new TransicionInvalidaError(
          apiErr.message || 'No se pueden registrar ingresos en este momento.',
        )
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Abre un nuevo turno de caja.
   * Transición: SIN_TURNO → OPERANDO
   */
  async abrirTurno(payload: AbrirTurnoPayload): Promise<TurnoActivoResponse> {
    try {
      return await turnoCajaApi.abrirTurno(payload)
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Carga el turno activo del cajero.
   * Lanza TurnoNoEncontradoError si no hay turno (null, o 404 de un backend viejo).
   */
  async cargarTurnoActivo(sucursalId?: string | null): Promise<TurnoActivoResponse> {
    let turno: TurnoActivoResponse | null
    try {
      turno = await turnoCajaApi.obtenerActivo(sucursalId)
    } catch (err) {
      const apiErr = err as ApiError
      if (apiErr.statusCode === 404) throw new TurnoNoEncontradoError()
      throw new Error(toMensajeError(err), { cause: err })
    }
    if (!turno) throw new TurnoNoEncontradoError()
    return turno
  },

  /**
   * Inicia el proceso de conteo.
   * Transición: OPERANDO → EN_CONTEO
   */
  async iniciarConteo(turnoId: string): Promise<TurnoActivoResponse> {
    try {
      return await turnoCajaApi.iniciarConteo(turnoId)
    } catch (err) {
      const apiErr = err as ApiError
      if (apiErr.statusCode === 409)
        throw new TransicionInvalidaError('El turno ya tiene un conteo en progreso.')
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Envía el conteo declarado por el cajero.
   * Transición: EN_CONTEO → ESPERANDO_REVISION
   */
  async enviarConteo(payload: ConteoPayload): Promise<TurnoActivoResponse> {
    try {
      return await turnoCajaApi.enviarConteo(payload)
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Valida las credenciales del administrador y revela el balance.
   * Transición: ESPERANDO_REVISION → BALANCE_REVELADO
   * Lanza CredencialesAdminInvalidasError, con el mensaje del backend, si el
   * PIN (o la contraseña, solo si el administrador aún no tiene PIN) no
   * coincide (403 CREDENCIALES_INVALIDAS, o 401 de un backend viejo). Los
   * demás rechazos (administrador de otra sucursal o sin permiso, dueño del
   * turno, demasiados intentos, turno ajeno) muestran el mensaje del backend.
   */
  async autenticarAdmin(payload: RevisionAdminPayload): Promise<RevisionAdminResponse> {
    try {
      return await turnoCajaApi.autenticarRevisionAdmin(payload)
    } catch (err) {
      const apiErr = err as ApiError
      if (apiErr.statusCode === 401 || CODIGOS_CREDENCIAL_INVALIDA.has(apiErr.code)) {
        throw new CredencialesAdminInvalidasError(apiErr.message)
      }
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  async validarPinCajero(turnoId: string, pin: string): Promise<ResultadoValidacionPin> {
    try {
      const resp = await turnoCajaApi.validarPinCajero(turnoId, pin)
      return { ok: resp.ok, tokenPin: resp.token_pin ?? null }
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Valida el PIN de un administrador. A16: el token que devuelve solo sirve
   * para `proposito` — `cerrar` en el cierre de caja, `cancelar` para cancelar
   * o devolver una orden cobrada.
   */
  async validarPinAdmin(
    turnoId: string,
    adminEmail: string,
    pin: string,
    proposito: PropositoPinAdmin,
  ): Promise<ResultadoValidacionPin> {
    try {
      const resp = await turnoCajaApi.validarPinAdmin(turnoId, adminEmail, pin, proposito)
      return { ok: resp.ok, tokenPin: resp.token_pin ?? null }
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Confirma el cierre del turno y genera el PDF de arqueo.
   * Transición: BALANCE_REVELADO → CERRADO
   */
  async confirmarCierre(payload: ConfirmarCierrePayload): Promise<ConfirmarCierreResponse> {
    try {
      return await turnoCajaApi.confirmarCierre(payload)
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Cancela el conteo en curso y regresa a OPERANDO.
   */
  async cancelarConteo(turnoId: string): Promise<TurnoActivoResponse> {
    try {
      return await turnoCajaApi.cancelarConteo(turnoId)
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Carga el historial de arqueos con filtros opcionales.
   */
  async listarHistorial(filtros: FiltrosHistorial = {}): Promise<HistorialArqueosResponse> {
    try {
      return await turnoCajaApi.listarHistorial(filtros)
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * KPIs agregados de todo el periodo filtrado del historial de arqueos
   * (no solo la página que se está mostrando).
   */
  async resumenHistorial(
    filtros: Omit<FiltrosHistorial, 'page' | 'pageSize'> = {},
  ): Promise<ResumenHistorialArqueos> {
    try {
      return await turnoCajaApi.resumenHistorial(filtros)
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Descarga el historial de arqueos (con los mismos filtros aplicados) como CSV.
   */
  async exportarHistorial(
    filtros: Omit<FiltrosHistorial, 'page' | 'pageSize'> = {},
    nombreArchivo = 'historial_arqueos.csv',
  ): Promise<void> {
    try {
      const blob = await turnoCajaApi.exportarHistorial(filtros)
      downloadBlob(blob, nombreArchivo)
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Carga el detalle completo de un arqueo para el modal de auditoría.
   */
  async obtenerDetalle(id: string): Promise<DetalleArqueo> {
    try {
      return await turnoCajaApi.obtenerDetalleArqueo(id)
    } catch (err) {
      const apiErr = err as ApiError
      if (apiErr.statusCode === 404)
        throw new Error('El arqueo solicitado no existe o fue eliminado.', { cause: err })
      throw new Error(toMensajeError(err), { cause: err })
    }
  },

  /**
   * Descarga el PDF de comprobante de un arqueo.
   * Usa downloadBlob para la descarga silenciosa sin abrir nueva pestaña.
   */
  async descargarPdfArqueo(id: string, nombreArchivo = `arqueo_${id}.pdf`): Promise<void> {
    try {
      const blob = await turnoCajaApi.descargarPdf(id)
      downloadBlob(blob, nombreArchivo)
    } catch (err) {
      throw new Error(toMensajeError(err), { cause: err })
    }
  },
}
