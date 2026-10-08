import { describe, it, expect, beforeEach, vi } from 'vitest'

const get = vi.fn()
vi.mock('@/api/axiosClient', () => ({ apiClient: { get } }))

const { usersApi } = await import('@/api/usersApi')

const RAW = {
  id: 'u1',
  full_name: 'Juan',
  apellidos: null,
  telefono: null,
  email: 'juan@test.com',
  role: 'Cajero',
  branch_id: 's1',
  is_active: false,
  ultimo_acceso: null,
}

describe('usersApi.list', () => {
  beforeEach(() => {
    get.mockReset()
    get.mockResolvedValue({ data: [RAW] })
  })

  it('manda el filtro de estado al backend', async () => {
    const users = await usersApi.list('todos')
    expect(get).toHaveBeenCalledWith('/usuarios', { params: { estado: 'todos' } })
    expect(users[0]).toMatchObject({ id: 'u1', isActive: false })
  })

  it('sin estado conserva el contrato de antes (solo activos en el backend)', async () => {
    await usersApi.list()
    expect(get).toHaveBeenCalledWith('/usuarios', { params: undefined })
  })
})
