export type TipoMovimientoManual = 'E' | 'M'

export interface MovimientoManualCreate {
  tipo: TipoMovimientoManual
  cantidad: string
  notas?: string | null
}

export interface ConteoFisicoCreate {
  stock_contado: string
  notas?: string | null
}

export interface MovimientoInventario {
  id: string
  sucursal_id: string
  insumo_id: string
  insumo_nombre: string
  tipo: string
  cantidad: string
  stock_resultante: string
  motivo: string
  referencia_id: string | null
  notas: string | null
  costo_total: string | null
  creado: string
  creado_por: string | null
}

export interface CogsRenglon {
  insumo_id: string
  insumo_nombre: string
  cantidad_salida: string
  costo_total: string
}

// KPIs del reporte de costo de ventas: ventas, margen y merma del periodo.
// margen = ventas - costo de ventas - merma; merma = manual + faltante de los
// conteos físicos (M24).
export interface ResumenCogs {
  ventasTotales: number
  costoVentas: number
  margen: number
  merma: number
  mermaManual: number
  mermaConteo: number
}
