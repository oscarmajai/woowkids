import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useReservacionesStore } from '@/stores/reservaciones'
import { reservacionesApi } from '@/api/reservacionesApi'
import type { Reservaciones } from '@/types/reservaciones'

vi.mock('@/api/reservacionesApi', () => ({
  reservacionesApi: { listar: vi.fn() },
}))

const listarMock = vi.mocked(reservacionesApi.listar)

const res = (id: string) => ({ id }) as Reservaciones

/** Promesa que el test resuelve cuando quiere, para simular respuestas desordenadas. */
function diferida<T>() {
  let resolver!: (v: T) => void
  const promesa = new Promise<T>((r) => (resolver = r))
  return { promesa, resolver }
}

describe('reservaciones store · cargar', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    listarMock.mockReset()
  })

  it('descarta la respuesta de una carga anterior que llega tarde', async () => {
    const store = useReservacionesStore()
    const octubre = diferida<Reservaciones[]>()
    const noviembre = diferida<Reservaciones[]>()
    listarMock.mockReturnValueOnce(octubre.promesa).mockReturnValueOnce(noviembre.promesa)

    const cargaOctubre = store.cargar('suc-1', '2026-09-28', '2026-11-08')
    const cargaNoviembre = store.cargar('suc-1', '2026-10-26', '2026-12-06')

    noviembre.resolver([res('nov')])
    await cargaNoviembre
    expect(store.loading).toBe(false)

    octubre.resolver([res('oct')])
    await cargaOctubre

    expect(store.reservaciones.map((r) => r.id)).toEqual(['nov'])
    expect(store.loading).toBe(false)
  })
})
