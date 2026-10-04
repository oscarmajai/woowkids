import { describe, expect, it } from 'vitest'
import { conexionInsegura, urlInstalarCertificado, urlSegura } from '@/utils/conexionSegura'

const UBICACION = {
  protocol: 'http:',
  host: '192.168.1.50:8080',
  hostname: '192.168.1.50',
  pathname: '/pos/caja',
  search: '?x=1',
}

describe('conexionSegura', () => {
  it('avisa solo fuera de un contexto seguro', () => {
    expect(conexionInsegura(false)).toBe(true)
    expect(conexionInsegura(true)).toBe(false)
  })

  it('propone la misma página por HTTPS', () => {
    expect(urlSegura(UBICACION)).toBe('https://192.168.1.50/pos/caja?x=1')
  })

  it('liga a la página del servidor para instalar el certificado', () => {
    expect(urlInstalarCertificado(UBICACION)).toBe('http://192.168.1.50:8080/instalar-certificado')
  })
})
