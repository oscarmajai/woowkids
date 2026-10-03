/**
 * Saludo según la hora local (0–23). La madrugada (antes de las 5) todavía es
 * "noche": a la 01:21 decía "Buenos días".
 */
export function saludoPorHora(hora: number): string {
  if (hora >= 5 && hora < 12) return 'Buenos días'
  if (hora >= 12 && hora < 19) return 'Buenas tardes'
  return 'Buenas noches'
}
