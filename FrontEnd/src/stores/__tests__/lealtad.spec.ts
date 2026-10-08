import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { apiClient } from '@/api/axiosClient'
import { useLealtadStore } from '@/stores/lealtad'

vi.mock('@/api/axiosClient', () => ({ apiClient: { get: vi.fn() } }))

const get = vi.mocked(apiClient.get)

describe('lealtad store · configuración de canje', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    get.mockReset()
  })

  it('lee el endpoint de solo lectura que permite lealtad:redimir', async () => {
    const config = { sucursal_id: 'suc-1', activo: true, valor_punto: 0.5, minimo_canje: 50 }
    get.mockResolvedValue({ data: config })
    const store = useLealtadStore()

    await expect(store.cargarConfiguracionCanje('suc-1')).resolves.toEqual(config)
    expect(get).toHaveBeenCalledWith('/lealtad/configuracion/canje', {
      params: { sucursal_id: 'suc-1' },
    })
    // No pisa la configuración completa que usa la página de administración.
    expect(store.configuracion).toBeNull()
  })

  it('deja pasar el error para que la caja deshabilite el canje', async () => {
    get.mockRejectedValue({ statusCode: 403, code: 'FORBIDDEN', message: 'Sin permiso' })
    const store = useLealtadStore()

    await expect(store.cargarConfiguracionCanje('suc-1')).rejects.toMatchObject({
      statusCode: 403,
    })
  })
})
