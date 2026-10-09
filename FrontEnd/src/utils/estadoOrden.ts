/**
 * ¿La orden está cancelada? El estado 'C' no significa lo mismo en cada origen:
 * en una comanda es "cancelada", pero en una estancia es "cerrada" (el niño ya
 * salió) y una estancia no se cancela. Las reservaciones usan 'cancelada'.
 */
export function ordenCancelada(
  tipoOrigen: 'comanda' | 'estancia' | 'reservacion' | undefined,
  estado: string | null | undefined,
): boolean {
  if (!estado) return false
  if (tipoOrigen === 'reservacion') return estado === 'cancelada'
  if (tipoOrigen === 'estancia') return false
  return estado === 'C'
}
