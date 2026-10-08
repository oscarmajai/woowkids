export interface TurnoActualCaja {
  id: string
  cajero: string
  apertura: string
}

export interface CajaAdmin {
  id: string
  nombre: string
  numero: number
  activo: boolean
  impresora: string | null
  turnoActual: TurnoActualCaja | null
  /** Sucursal de la caja (útil en la vista "Todas las sucursales"). */
  sucursalId?: string | null
  sucursalNombre?: string | null
}

export interface CajaCreate {
  nombre: string
  numero: number
  impresora?: string | null
}

export interface CajaUpdate {
  nombre?: string
  numero?: number
  activo?: boolean
  impresora?: string | null
}
