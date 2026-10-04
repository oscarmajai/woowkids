import type { BloqueAviso } from '@/types/privacidad'

/**
 * Convierte el texto del aviso de privacidad en bloques para mostrarlo sin
 * v-html (el texto lo edita un administrador): "# " título, "## " sección,
 * líneas con "- " son viñetas y el resto son párrafos separados por una
 * línea en blanco.
 */
export function parsearAviso(texto: string): BloqueAviso[] {
  const bloques: BloqueAviso[] = []
  let parrafo: string[] = []
  let lista: string[] = []

  const cerrarParrafo = () => {
    if (parrafo.length) bloques.push({ tipo: 'parrafo', texto: parrafo.join(' ') })
    parrafo = []
  }
  const cerrarLista = () => {
    if (lista.length) bloques.push({ tipo: 'lista', items: lista })
    lista = []
  }

  for (const cruda of texto.replace(/\r\n?/g, '\n').split('\n')) {
    const linea = cruda.trim()
    if (!linea) {
      cerrarParrafo()
      cerrarLista()
    } else if (linea.startsWith('## ')) {
      cerrarParrafo()
      cerrarLista()
      bloques.push({ tipo: 'seccion', texto: linea.slice(3).trim() })
    } else if (linea.startsWith('# ')) {
      cerrarParrafo()
      cerrarLista()
      bloques.push({ tipo: 'titulo', texto: linea.slice(2).trim() })
    } else if (linea.startsWith('- ')) {
      cerrarParrafo()
      lista.push(linea.slice(2).trim())
    } else {
      cerrarLista()
      parrafo.push(linea)
    }
  }
  cerrarParrafo()
  cerrarLista()
  return bloques
}

/** Ruta pública del aviso integral (router). */
export const RUTA_AVISO_PRIVACIDAD = '/aviso-de-privacidad'
