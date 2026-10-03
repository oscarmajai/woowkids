/**
 * Nombre del CSV de indicadores de una sucursal: lleva la sucursal y el
 * periodo para que se sepa de qué es al abrirlo (el contenido también los
 * trae). Mismo formato que el backend.
 */
export function nombreArchivoIndicadores(
  clave: string | null | undefined,
  desde: string,
  hasta: string,
): string {
  const identificador = clave?.trim() || 'sucursal'
  return `indicadores_${identificador}_${desde}_${hasta}.csv`
}
