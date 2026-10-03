import AuditFields from '@/types/shared'

export type EstadoReservacion = 'pendiente' | 'confirmada' | 'en_curso' | 'completada' | 'cancelada'

export interface Reservaciones extends AuditFields {
  folio: string | null
  sucursal_id: string
  tipo_evento_id: string
  paquete_id: string
  nombre_cliente: string
  apellidos_cliente: string | null
  telefono_cliente: string
  email_cliente: string | null
  nombre_festejado: string | null
  edad_festejado: number | null
  fecha_evento: string
  hora_inicio: string
  hora_fin: string
  numero_personas: number
  precio_base: string
  precio_personas_extra: string
  horas_reservadas: number
  precio_horas: string
  precio_productos: string
  precio_extras: string
  descuento: string
  precio_total: string
  /** Lo cobrado al levantar la reservación (histórico). */
  anticipo: string
  /** Neto cobrado: todos los pagos menos el cambio devuelto (migración 075). */
  monto_pagado: string
  /** precio_total - monto_pagado, calculado por la BD. */
  saldo_pendiente: string
  estado: EstadoReservacion
  comanda_enviada: boolean
  notas: string | null
}

export interface ReservacionesCreate {
  sucursal_id: string
  tipo_evento_id: string
  paquete_id: string
  nombre_cliente: string
  apellidos_cliente?: string | null
  telefono_cliente: string
  email_cliente?: string | null
  nombre_festejado?: string | null
  edad_festejado?: number | null
  fecha_evento: string
  hora_inicio: string
  hora_fin: string
  numero_personas: number
  precio_base: string
  precio_personas_extra?: string
  horas_reservadas?: number
  precio_horas?: string
  precio_productos?: string
  precio_extras?: string
  descuento?: string
  precio_total: string
  anticipo?: string
  estado?: EstadoReservacion
  notas?: string | null
}

export interface ReservacionesUpdate {
  nombre_cliente?: string | null
  apellidos_cliente?: string | null
  telefono_cliente?: string | null
  email_cliente?: string | null
  nombre_festejado?: string | null
  edad_festejado?: number | null
  fecha_evento?: string | null
  hora_inicio?: string | null
  hora_fin?: string | null
  numero_personas?: number | null
  horas_reservadas?: number | null
  /**
   * Al cambiar invitados u horas el servidor recalcula pulseras y total; estos
   * dos solo se comparan (409 si no coinciden). El resto del precio y el
   * anticipo ya no se editan por aquí.
   */
  precio_personas_extra?: string | null
  precio_total?: string | null
  estado?: EstadoReservacion | null
  notas?: string | null
  activo?: boolean
}

export interface EventoDelDia {
  id: string
  folio: string | null
  nombre_cliente: string
  apellidos_cliente: string | null
  telefono_cliente: string
  hora_inicio: string
  hora_fin: string
  numero_personas: number
}

export interface BloqueDisponibilidad {
  hora_inicio: string
  hora_fin: string
  ocupado: boolean
  reservacion_id: string | null
}

export interface Disponibilidad {
  sucursal_id: string
  fecha: string
  bloques: BloqueDisponibilidad[]
}
