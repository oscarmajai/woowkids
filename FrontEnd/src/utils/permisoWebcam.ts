/**
 * Webcam por HTTP en la red local.
 *
 * Chrome y Edge solo dan la webcam (getUserMedia) en un contexto seguro: HTTPS
 * o localhost. Por HTTP desde otra computadora ni siquiera preguntan. La
 * política OverrideSecurityRestrictionsOnInsecureOrigin de ambos navegadores
 * trata un origen HTTP como seguro: con ella, al tomar la foto el navegador
 * solo pide "Permitir". Aquí se arma el archivo .reg que la aplica en Windows
 * (una vez por computadora; en un dominio se reparte por GPO).
 */

const LLAVES = [
  'HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Google\\Chrome\\OverrideSecurityRestrictionsOnInsecureOrigin',
  'HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Microsoft\\Edge\\OverrideSecurityRestrictionsOnInsecureOrigin',
]

export const NOMBRE_ARCHIVO_WEBCAM = 'habilitar-webcam-woowkids.reg'

/** Tabletas y teléfonos: abren su propia cámara sin necesitar nada. */
export function esDispositivoTactil(win: Pick<Window, 'matchMedia'> = window): boolean {
  return win.matchMedia?.('(pointer: coarse)').matches ?? false
}

/** Contenido del .reg para que Chrome y Edge permitan la webcam en `origen`. */
export function contenidoRegistroWebcam(origen: string): string {
  const valor = origen.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  const bloques = LLAVES.map((llave) => `[${llave}]\r\n"1"="${valor}"\r\n`)
  return `Windows Registry Editor Version 5.00\r\n\r\n${bloques.join('\r\n')}`
}

/** El .reg en UTF-16LE con BOM, la codificación que espera regedit. */
export function archivoRegistroWebcam(origen: string): Blob {
  const texto = contenidoRegistroWebcam(origen)
  const unidades = new Uint16Array(texto.length + 1)
  unidades[0] = 0xfeff
  for (let i = 0; i < texto.length; i++) unidades[i + 1] = texto.charCodeAt(i)
  return new Blob([unidades], { type: 'application/octet-stream' })
}

export function descargarRegistroWebcam(origen: string = window.location.origin): void {
  const url = URL.createObjectURL(archivoRegistroWebcam(origen))
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = NOMBRE_ARCHIVO_WEBCAM
  document.body.appendChild(enlace)
  enlace.click()
  enlace.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
