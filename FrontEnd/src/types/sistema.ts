/** GET /api/sistema/respaldos — último respaldo automático (solo AdministradorSistema). */
export interface EstadoRespaldos {
  alerta: boolean
  mensaje: string | null
  ultimoExitoso: string | null
}
