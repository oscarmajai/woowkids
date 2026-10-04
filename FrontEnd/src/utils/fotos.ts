/**
 * Fotos del registro de entrada (INE y llegada).
 *
 * La webcam dentro de la página (getUserMedia) solo existe en un contexto
 * seguro (HTTPS o localhost). El sistema se usa por HTTP en la red local, así
 * que sin ella se toma la foto con la cámara del dispositivo o se elige un
 * archivo, y se normaliza como las de la webcam.
 */

/** Lado mayor de la foto guardada: igual que la captura de la webcam (1280×720). */
export const LADO_MAXIMO = 1280

export function camaraEnPaginaDisponible(nav: Navigator = navigator): boolean {
  return typeof nav.mediaDevices?.getUserMedia === 'function'
}

/** Medidas para que el lado mayor no pase de `maximo`, sin agrandar. */
export function medidasReducidas(
  ancho: number,
  alto: number,
  maximo = LADO_MAXIMO,
): { ancho: number; alto: number } {
  const escala = Math.min(1, maximo / Math.max(ancho, alto))
  return { ancho: Math.round(ancho * escala), alto: Math.round(alto * escala) }
}

/**
 * JPEG de máximo LADO_MAXIMO px: la foto del teléfono pesa varios MB y la API
 * acepta hasta 5 MB. Si el navegador no puede procesarla se devuelve tal cual
 * (la API valida tipo y tamaño).
 */
export async function normalizarFoto(original: File, nombre: string): Promise<File> {
  try {
    const imagen = await createImageBitmap(original)
    const { ancho, alto } = medidasReducidas(imagen.width, imagen.height)
    const canvas = document.createElement('canvas')
    canvas.width = ancho
    canvas.height = alto
    const ctx = canvas.getContext('2d')
    if (!ctx) return original
    ctx.drawImage(imagen, 0, 0, ancho, alto)
    imagen.close()
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', 0.9),
    )
    if (!blob) return original
    return new File([blob], nombre, { type: 'image/jpeg', lastModified: Date.now() })
  } catch {
    return original
  }
}
