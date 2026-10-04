import { describe, expect, it } from 'vitest'
import {
  contenidoActivador,
  esDispositivoTactil,
  esWindows,
  navegadorActual,
} from '@/utils/activarWebcam'

const ORIGEN = 'http://192.168.100.82:8080'
const PAGINA = `${ORIGEN}/estancias/registro-infantes`

describe('activador de la webcam', () => {
  const cmd = contenidoActivador(ORIGEN, PAGINA, 'chrome')

  it('aplica la política en Chrome y en Edge para el origen del servidor', () => {
    expect(cmd).toContain(`set "ORIGEN=${ORIGEN}"`)
    expect(cmd).toContain(
      'HKLM\\SOFTWARE\\Policies\\Google\\Chrome\\OverrideSecurityRestrictionsOnInsecureOrigin',
    )
    expect(cmd).toContain(
      'HKLM\\SOFTWARE\\Policies\\Microsoft\\Edge\\OverrideSecurityRestrictionsOnInsecureOrigin',
    )
    expect(cmd).toContain('reg add "%~1" /v %N% /t REG_SZ /d "%ORIGEN%" /f')
  })

  it('solo el registro corre como administrador; el navegador se reabre sin elevar', () => {
    expect(cmd).toContain("-ArgumentList '/permisos' -Verb RunAs -Wait")
    const permisos = cmd.indexOf('\r\n:permisos\r\n')
    const reinicio = cmd.indexOf('start "" %NAVEGADOR% "%PAGINA%"')
    expect(reinicio).toBeGreaterThan(0)
    expect(reinicio).toBeLessThan(permisos)
  })

  it('usa CRLF y reabre el navegador en el registro de entrada', () => {
    expect(cmd.includes('\n') && !/[^\r]\n/.test(cmd)).toBe(true)
    expect(cmd).toContain(`set "PAGINA=${PAGINA}"`)
    expect(contenidoActivador(ORIGEN, PAGINA, 'msedge')).toContain('set "NAVEGADOR=msedge"')
  })

  it('rechaza direcciones con caracteres que romperían el archivo', () => {
    expect(() => contenidoActivador('http://x" & del *', PAGINA, 'chrome')).toThrow()
  })

  it('detecta el navegador y el sistema', () => {
    const edge = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Safari/537.36 Edg/141.0'
    const chrome = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0 Safari/537.36'
    expect(navegadorActual(edge)).toBe('msedge')
    expect(navegadorActual(chrome)).toBe('chrome')
    expect(esWindows(chrome)).toBe(true)
    expect(esWindows('Mozilla/5.0 (X11; Linux x86_64)')).toBe(false)
    expect(
      esDispositivoTactil({ matchMedia: () => ({ matches: true }) } as unknown as Window),
    ).toBe(true)
  })
})
