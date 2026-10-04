/**
 * Webcam por HTTP en la red local.
 *
 * Chrome y Edge solo dan la webcam (getUserMedia) en un contexto seguro: HTTPS
 * o localhost. Por HTTP desde otra computadora ni siquiera muestran el
 * "Permitir". Su política OverrideSecurityRestrictionsOnInsecureOrigin trata
 * un origen HTTP como seguro, y con ella el navegador vuelve a preguntar y
 * basta con permitir.
 *
 * Una página no puede cambiar eso por sí sola, así que se descarga un
 * activador (.cmd) hecho para la dirección de este servidor: pide el permiso
 * de Windows, aplica la política en Chrome y Edge, y reinicia el navegador
 * (sin privilegios de administrador) en el registro de entrada. Una vez por
 * computadora; en un dominio, sistemas puede aplicar la misma política por GPO.
 * Con HTTPS no hace falta nada de esto.
 */

export const NOMBRE_ACTIVADOR = 'activar-webcam-woowkids.cmd'

export type Navegador = 'chrome' | 'msedge'

/** Tabletas y teléfonos: abren su propia cámara sin necesitar nada. */
export function esDispositivoTactil(win: Pick<Window, 'matchMedia'> = window): boolean {
  return win.matchMedia?.('(pointer: coarse)').matches ?? false
}

export function esWindows(userAgent: string = navigator.userAgent): boolean {
  return /Windows/i.test(userAgent)
}

export function navegadorActual(userAgent: string = navigator.userAgent): Navegador {
  return /Edg\//.test(userAgent) ? 'msedge' : 'chrome'
}

/** Origen y página sin caracteres que rompan el .cmd (", %, ^, &, |, <, >). */
function seguroParaCmd(valor: string): string {
  if (/["%^&|<>\r\n]/.test(valor)) throw new Error(`Valor no válido para el activador: ${valor}`)
  return valor
}

/** Texto del activador (.cmd, con CRLF: cmd falla con etiquetas en saltos LF). */
export function contenidoActivador(origen: string, pagina: string, navegador: Navegador): string {
  const lineas = [
    '@echo off',
    'rem Woow Kids: permite la webcam en Chrome y Edge para este servidor (HTTP en la red local).',
    'rem Aplica la politica OverrideSecurityRestrictionsOnInsecureOrigin y reinicia el navegador.',
    'setlocal EnableExtensions',
    `set "ORIGEN=${seguroParaCmd(origen)}"`,
    `set "PAGINA=${seguroParaCmd(pagina)}"`,
    `set "NAVEGADOR=${navegador}"`,
    'set "CHROME=HKLM\\SOFTWARE\\Policies\\Google\\Chrome\\OverrideSecurityRestrictionsOnInsecureOrigin"',
    'set "EDGE=HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge\\OverrideSecurityRestrictionsOnInsecureOrigin"',
    'if /i "%~1"=="/permisos" goto :permisos',
    '',
    'echo Activando la webcam de Woow Kids en esta computadora...',
    'echo Windows te pedira permiso: elige Si.',
    "powershell -NoProfile -ExecutionPolicy Bypass -Command \"try { Start-Process -FilePath '%~f0' -ArgumentList '/permisos' -Verb RunAs -Wait -WindowStyle Hidden; exit 0 } catch { exit 1 }\"",
    'reg query "%CHROME%" 2>nul | find /i "%ORIGEN%" >nul',
    'if errorlevel 1 (',
    '  echo.',
    '  echo No se pudo activar: hace falta el permiso de administrador de Windows.',
    '  echo Vuelve a abrir el archivo y elige Si, o pide ayuda a sistemas.',
    '  pause',
    '  exit /b 1',
    ')',
    'echo Listo. Reiniciando el navegador...',
    'taskkill /im %NAVEGADOR%.exe >nul 2>&1',
    'timeout /t 3 /nobreak >nul',
    'taskkill /im %NAVEGADOR%.exe /f >nul 2>&1',
    'timeout /t 1 /nobreak >nul',
    'start "" %NAVEGADOR% "%PAGINA%"',
    'exit /b 0',
    '',
    ':permisos',
    'call :permitir "%CHROME%"',
    'call :permitir "%EDGE%"',
    'exit /b 0',
    '',
    'rem Agrega ORIGEN a la lista sin pisar entradas que ya existan (1, 2, ...).',
    ':permitir',
    'set "N="',
    'for /l %%i in (1,1,50) do if not defined N (',
    '  reg query "%~1" /v %%i 2>nul | find /i "%ORIGEN%" >nul && set "N=%%i"',
    ')',
    'for /l %%i in (1,1,50) do if not defined N (',
    '  reg query "%~1" /v %%i >nul 2>&1 || set "N=%%i"',
    ')',
    'reg add "%~1" /v %N% /t REG_SZ /d "%ORIGEN%" /f >nul',
    'exit /b 0',
    '',
  ]
  return lineas.join('\r\n')
}

export function descargarActivador(
  pagina: string = window.location.href,
  origen: string = window.location.origin,
): void {
  const texto = contenidoActivador(origen, pagina, navegadorActual())
  const url = URL.createObjectURL(new Blob([texto], { type: 'application/octet-stream' }))
  const enlace = document.createElement('a')
  enlace.href = url
  enlace.download = NOMBRE_ACTIVADOR
  document.body.appendChild(enlace)
  enlace.click()
  enlace.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
