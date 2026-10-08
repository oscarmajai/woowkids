import { describe, it, expect, beforeEach, vi } from 'vitest'

const post = vi.fn()
vi.mock('@/api/axiosClient', () => ({ apiClient: { post, get: vi.fn() } }))
vi.mock('@/api/metodosPagoApi', () => ({ metodosPagoApi: { listar: vi.fn() } }))

const { pagarExtra } = await import('@/api/onboardingClient')

describe('pagarExtra', () => {
  beforeEach(() => {
    post.mockReset()
    post.mockResolvedValue({ data: null })
  })

  it('manda el objeto { pagos, cambio } que espera el backend, no la lista suelta', async () => {
    const pagos = [{ metodoPagoId: 'm1', monto: 50 }]
    await pagarExtra('r1', 's1', pagos)

    expect(post).toHaveBeenCalledWith(
      '/estancias/r1/pagos',
      { pagos, cambio: 0 },
      { params: { sucursal_id: 's1' } },
    )
    expect(Array.isArray(post.mock.calls[0][1])).toBe(false)
  })

  it('incluye el cambio entregado', async () => {
    await pagarExtra('r1', 's1', [{ metodoPagoId: 'm1', monto: 100 }], 20)
    expect(post.mock.calls[0][1]).toMatchObject({ cambio: 20 })
  })
})
