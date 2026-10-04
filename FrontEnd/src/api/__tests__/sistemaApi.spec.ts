import { describe, it, expect, beforeEach, vi } from 'vitest'

const get = vi.fn()
vi.mock('@/api/axiosClient', () => ({ apiClient: { get } }))

const { sistemaApi } = await import('@/api/sistemaApi')

describe('sistemaApi.estadoRespaldos', () => {
  beforeEach(() => get.mockReset())

  it('trae el aviso y la fecha del último respaldo exitoso', async () => {
    get.mockResolvedValue({
      data: {
        alerta: true,
        mensaje: 'El último respaldo automático falló.',
        ultimo_exitoso: { inicio: '2026-10-03T20:00:00Z', exitoso: true },
        ultimo_intento: { inicio: '2026-10-04T02:00:00Z', exitoso: false },
      },
    })

    const estado = await sistemaApi.estadoRespaldos()

    expect(get).toHaveBeenCalledWith('/sistema/respaldos')
    expect(estado).toEqual({
      alerta: true,
      mensaje: 'El último respaldo automático falló.',
      ultimoExitoso: '2026-10-03T20:00:00Z',
    })
  })

  it('sin respaldos todavía deja la fecha vacía', async () => {
    get.mockResolvedValue({
      data: {
        alerta: true,
        mensaje: 'Todavía no hay…',
        ultimo_exitoso: null,
        ultimo_intento: null,
      },
    })

    expect((await sistemaApi.estadoRespaldos()).ultimoExitoso).toBeNull()
  })
})
