import { describe, expect, it } from 'vitest'
import {
  archivoRegistroWebcam,
  contenidoRegistroWebcam,
  esDispositivoTactil,
} from '@/utils/permisoWebcam'

describe('permiso de webcam por HTTP', () => {
  it('el .reg trata el origen del sistema como seguro en Chrome y en Edge', () => {
    const reg = contenidoRegistroWebcam('http://192.168.100.82:8080')
    expect(reg.startsWith('Windows Registry Editor Version 5.00\r\n')).toBe(true)
    expect(reg).toContain(
      '[HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Google\\Chrome\\OverrideSecurityRestrictionsOnInsecureOrigin]\r\n"1"="http://192.168.100.82:8080"',
    )
    expect(reg).toContain(
      '[HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Microsoft\\Edge\\OverrideSecurityRestrictionsOnInsecureOrigin]\r\n"1"="http://192.168.100.82:8080"',
    )
  })

  it('el archivo va en UTF-16LE con BOM, como lo espera regedit', async () => {
    const bytes = new Uint8Array(await archivoRegistroWebcam('http://x:1').arrayBuffer())
    expect([bytes[0], bytes[1]]).toEqual([0xff, 0xfe])
    expect([bytes[2], bytes[3]]).toEqual(['W'.charCodeAt(0), 0])
  })

  it('distingue tabletas y teléfonos de las computadoras', () => {
    const tactil = { matchMedia: () => ({ matches: true }) } as unknown as Window
    const raton = { matchMedia: () => ({ matches: false }) } as unknown as Window
    expect(esDispositivoTactil(tactil)).toBe(true)
    expect(esDispositivoTactil(raton)).toBe(false)
  })
})
