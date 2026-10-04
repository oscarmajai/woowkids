// ─────────────────────────────────────────────────────────────────────────────
// Módulo: Cierre de Caja — Tipos estrictos
// Espejo 1-a-1 del modelo del backend (FastAPI / PostgreSQL)
// ─────────────────────────────────────────────────────────────────────────────

// ---------------------------------------------------------------------------
// Máquina de estados
// ---------------------------------------------------------------------------

/** Estados del ciclo de vida de un turno de caja. */
export type EstadoTurno =
  | 'SIN_TURNO' // no hay turno activo / listo para apertura de caja
  | 'OPERANDO' // turno activo, aún no se inicia el conteo
  | 'EN_CONTEO' // cajero registrando denominaciones
  | 'ESPERANDO_REVISION' // conteo enviado, esperando autenticación del admin
  | 'BALANCE_REVELADO' // admin autenticado, diferencias visibles
  | 'CERRADO' // cierre confirmado y persistido

export interface TurnoItem {
  id: string
  nombre: string
  horaInicio?: string
  horaFin?: string
  /** M8: el horario corresponde a la hora local actual de la sucursal. */
  vigente?: boolean
}

export interface CajaItem {
  id: string
  codigo: string
  nombre: string
}

export interface AbrirTurnoPayload {
  fondoInicial: number
  terminal?: string
  observacionesApertura?: string
  turnoId?: string
  cajaId?: string
  /** Solo relevante para AdministradorSistema, que no tiene sucursal propia en el JWT. */
  sucursalId?: string
  /** PIN del cajero (o su contraseña, si aún no tiene PIN configurado). */
  pin?: string
}

// ---------------------------------------------------------------------------
// Denominaciones de efectivo
// ---------------------------------------------------------------------------

export interface DenominacionBillete {
  value: 1000 | 500 | 200 | 100 | 50 | 20
  amount: number | null
}

export interface DenominacionMoneda {
  value: 20 | 10 | 5 | 2 | 1 | 0.5
  label: string
  amount: number | null
}

export interface DesgloseEfectivo {
  billetes: DenominacionBillete[]
  monedas: DenominacionMoneda[]
  /** Calculado reactivamente; no se serializa al backend */
  total: number
}

// ---------------------------------------------------------------------------
// Métodos de pago
// ---------------------------------------------------------------------------

/** Una fila del formulario de declaración de métodos. `metodo` es el nombre real
 *  del catálogo de la BD (metodos_pago.nombre) — no hay claves fijas. */
export interface FilaMetodoPago {
  /** ID local único (UUID generado en frontend) para key de v-for */
  id: string
  metodo: string
  monto: number | null
  /** 'sistema': detectado automáticamente por tener movimientos reales en el turno (nombre fijo).
   *  'manual': agregado por el cajero eligiendo del catálogo. */
  origen: 'sistema' | 'manual'
}

/** M7: lo cobrado en el turno por método (el efectivo, neto del cambio). */
export interface VentaPorMetodo {
  metodo: string
  label: string
  total: number
}

/** B23: el conteo que el cajero ya envió, congelado hasta la revisión. */
export interface ConteoGuardado {
  desgloseEfectivo: {
    billetes: Array<{ denominacion: number; cantidad: number }>
    monedas: Array<{ denominacion: number; cantidad: number }>
    total: number
  }
  metodosPago: Array<{ metodo: string; monto: number }>
  totalDeclarado: number
}

/** Movimiento real del turno — viene del backend al cargar el turno activo */
export interface MovimientoTurno {
  metodo: string
  /** Total de ventas procesadas por este método durante el turno */
  totalVentas: number
}

// ---------------------------------------------------------------------------
// Balance comparativo (admin)
// ---------------------------------------------------------------------------

export interface FilaBalance {
  metodo: string
  label: string
  /** Monto declarado por el cajero */
  declarado: number
  /** Monto esperado según el sistema */
  esperado: number
  /** declarado − esperado (positivo = sobrante, negativo = faltante) */
  diferencia: number
  /** A4: lo devuelto a clientes con este método en el turno (ya restado de `esperado`). */
  devoluciones: number
}

// ---------------------------------------------------------------------------
// Turno activo — respuesta del backend al montar la página
// ---------------------------------------------------------------------------

export interface TurnoActivoResponse {
  id: string
  sucursalId: string
  sucursalNombre: string
  cajeroId: string
  cajeroNombre: string
  terminal: string
  /** Nombre de la caja ("Caja Patria 1"); `terminal` es el código ("CAJA 01"). */
  cajaNombre?: string | null
  estado: EstadoTurno
  fondoInicial: number
  fechaApertura: string // ISO 8601
  /** B13: notas capturadas al abrir la caja. */
  observacionesApertura?: string | null
  /** Bruto: lo recibido, incluido el efectivo que se devolvió como cambio. */
  totalVentas: number
  totalRetiros: number
  totalIngresos: number
  /** M6: "vendido en turno": número de tickets (no de pagos) y lo aplicado
   * (recibido menos cambio, como el esperado del arqueo). */
  numeroVentas: number
  totalVendido: number
  totalCambio?: number
  /** M7: efectivo que debería haber en el cajón ahora (negativo = caja en negativo).
   * `null` si el backend no lo manda (versiones viejas). */
  efectivoEsperado?: number | null
  ventasPorMetodo?: VentaPorMetodo[]
  movimientos: MovimientoTurno[]
  /** B23: solo con el conteo ya enviado (ESPERANDO_REVISION / BALANCE_REVELADO). */
  conteoGuardado?: ConteoGuardado | null
  /** Solo poblado por el backend cuando estado === 'BALANCE_REVELADO' (QA #8). */
  adminEmail?: string | null
  /** Solo poblado por el backend cuando estado === 'BALANCE_REVELADO' (QA #8). */
  balancePorMetodo?: FilaBalance[]
}

// ---------------------------------------------------------------------------
// Payload de conteo del cajero → POST /conteo
// ---------------------------------------------------------------------------

export interface ConteoPayload {
  turnoId: string
  desgloseEfectivo: {
    billetes: Array<{ denominacion: number; cantidad: number }>
    monedas: Array<{ denominacion: number; cantidad: number }>
    total: number
  }
  metodosPago: Array<{ metodo: string; monto: number }>
  totalDeclarado: number
}

// ---------------------------------------------------------------------------
// Payload de autenticación del administrador → POST /revision-admin
// ---------------------------------------------------------------------------

export interface RevisionAdminPayload {
  turnoId: string
  adminEmail: string
  adminPassword: string
}

export interface RevisionAdminResponse {
  autorizado: boolean
  adminNombre: string
  balancePorMetodo: FilaBalance[]
  totalEsperado: number
  totalDeclarado: number
  diferenciaNeta: number
}

// ---------------------------------------------------------------------------
// Payload de confirmación final → POST /confirmar
// ---------------------------------------------------------------------------

export type TipoCierre = 'NORMAL' | 'EXTRAORDINARIO'

export interface ConfirmarCierrePayload {
  turnoId: string
  observaciones: string
  tipoCierre?: TipoCierre
  /** Tokens de un solo uso emitidos al validar cada PIN (doble firma, QA #14). */
  tokenPinCajero?: string | null
  tokenPinAdmin?: string | null
}

/**
 * A16: para qué se emite el token del PIN de administrador. Cada token solo
 * sirve para su propósito: `cerrar` (revisión y confirmación del cierre de
 * caja) o `cancelar` (cancelar o devolver una orden cobrada).
 */
export type PropositoPinAdmin = 'cerrar' | 'cancelar'

/** Resultado de validar un PIN: el backend emite un token de un solo uso (5 min). */
export interface ResultadoValidacionPin {
  ok: boolean
  tokenPin: string | null
}

export interface ConfirmarCierreResponse {
  arqueoId: string
  estado: 'CERRADO'
  pdfUrl: string | null
  mensaje: string
}

/** Resultado de `confirmarCierre` del store: nunca lanza, el consumidor debe revisar `ok`. */
export type ResultadoCierre =
  { ok: true; pdfUrl: string | null; arqueoId: string } | { ok: false; error: string }

/**
 * Resultado de `cargarTurnoActivo` del store. Nunca lanza.
 * - `{ ok: true, hayTurno: true }`: turno cargado.
 * - `{ ok: true, hayTurno: false }`: el backend confirmó (404) que no hay turno.
 * - `{ ok: false, error }`: la carga falló (red, 5xx, 403...); se conserva el estado previo.
 */
export type ResultadoCargaTurno = { ok: true; hayTurno: boolean } | { ok: false; error: string }

// ---------------------------------------------------------------------------
// Retiros parciales (RN-RET)
// ---------------------------------------------------------------------------

/** Valores reales del enum conceptos_retiro en BD */
export type ConceptoRetiro =
  | 'Pago a proveedor'
  | 'Compra de insumos'
  | 'Depósito bancario'
  | 'Resguardo de efectivo'
  | 'Pago de servicios'
  | 'Gastos administrativos'
  | 'Gastos varios'
  | 'Devolución'

/** Valores reales del enum tipos_destinatario en BD */
export type TipoDestinatario = 'Proveedor' | 'Empleado' | 'Administrador' | 'Cliente'

export interface RetiroParcialPayload {
  turnoId: string
  concepto: ConceptoRetiro
  tipoDestinatario: TipoDestinatario
  monto: number
  observaciones?: string
}

export interface RetiroParcialResponse {
  id: string
  turnoId: string
  concepto: string
  tipoDestinatario: string
  monto: number
  observaciones: string | null
  creado: string
}

export interface IngresoEfectivoPayload {
  turnoId: string
  monto: number
  /** Motivo del ingreso (opcional). */
  observaciones?: string
}

export interface IngresoEfectivoResponse {
  id: string
  turnoId: string
  monto: number
  observaciones?: string | null
  creado: string
}

// ---------------------------------------------------------------------------
// Historial de arqueos
// ---------------------------------------------------------------------------

export interface FiltrosHistorial {
  sucursalId?: string
  cajeroId?: string
  fechaDesde?: string // YYYY-MM-DD
  fechaHasta?: string
  page?: number
  pageSize?: number
}

export interface ArqueoResumen {
  id: string
  cajeroNombre: string
  terminal: string
  cajaNombre?: string | null
  sucursalNombre: string
  fechaApertura: string
  fechaCierre: string
  fondoInicial: number
  totalDeclarado: number
  totalEsperado: number
  diferenciaNeta: number
  tieneObservaciones: boolean
  pdfUrl: string | null
  adminNombre?: string | null
}

export interface HistorialArqueosResponse {
  items: ArqueoResumen[]
  total: number
  page: number
  pageSize: number
}

// KPIs agregados de TODO el periodo filtrado (no solo la página cargada).
export interface ResumenHistorialArqueos {
  totalArqueos: number
  totalDeclarado: number
  totalEsperado: number
  diferenciaNeta: number
  arqueosConDiferencia: number
}

export interface DetalleArqueo extends ArqueoResumen {
  desgloseEfectivo: {
    billetes: Array<{ denominacion: number; cantidad: number; subtotal: number }>
    monedas: Array<{ denominacion: number; cantidad: number; subtotal: number }>
    totalEfectivo: number
  }
  balancePorMetodo: FilaBalance[]
  observaciones: string
  adminNombre: string
  /** B13: notas de la apertura de caja. */
  observacionesApertura?: string | null
  /** Ingresos de efectivo del turno, con su motivo. */
  ingresos?: Array<{ id: string; monto: number; observaciones: string | null; creado: string }>
  /** A4: devoluciones a clientes registradas en el turno. */
  devoluciones?: DevolucionArqueo[]
}

/** A4: de dónde salió una devolución: cancelar una orden cobrada (su stock
 * regresó) o devolver una ya entregada (el stock no regresa). */
export type OrigenDevolucion = 'cancelacion' | 'entregada'

/** A4: devolución a un cliente que resta del esperado de su método en el arqueo. */
export interface DevolucionArqueo {
  id: string
  comandaId: string
  ticketNumero: string | null
  metodoPagoNombre: string | null
  esEfectivo: boolean
  monto: number
  origen: OrigenDevolucion
  motivo: string | null
  autorizadoPorNombre: string | null
  creadoPorNombre: string | null
  creado: string
}
