import { defineStore } from 'pinia'
import { ref } from 'vue'
import { privacidadService } from '@/services/privacidadService'
import type {
  AvisoPrivacidad,
  AvisoPrivacidadAdmin,
  PublicarAvisoPayload,
} from '@/types/privacidad'
import type { ApiError } from '@/types/auth'

function mensajeDe(err: unknown, porDefecto: string): string {
  return (err as Partial<ApiError> | null)?.message || porDefecto
}

/** Aviso de privacidad: la versión vigente (pública) y su administración. */
export const useAvisoPrivacidadStore = defineStore('avisoPrivacidad', () => {
  const vigente = ref<AvisoPrivacidad | null>(null)
  const cargandoVigente = ref(false)
  const errorVigente = ref<string | null>(null)

  const admin = ref<AvisoPrivacidadAdmin | null>(null)
  const cargandoAdmin = ref(false)
  const errorAdmin = ref<string | null>(null)
  const publicando = ref(false)

  async function cargarVigente(): Promise<void> {
    cargandoVigente.value = true
    errorVigente.value = null
    try {
      vigente.value = await privacidadService.obtenerVigente()
    } catch (err) {
      errorVigente.value = mensajeDe(err, 'No se pudo cargar el aviso de privacidad.')
    } finally {
      cargandoVigente.value = false
    }
  }

  async function cargarAdmin(): Promise<void> {
    cargandoAdmin.value = true
    errorAdmin.value = null
    try {
      admin.value = await privacidadService.obtenerAdmin()
    } catch (err) {
      errorAdmin.value = mensajeDe(err, 'No se pudo cargar el aviso de privacidad.')
    } finally {
      cargandoAdmin.value = false
    }
  }

  /** Publica una versión nueva. Lanza el ApiError (p. ej. 409) para que la página lo muestre. */
  async function publicar(cambios: Omit<PublicarAvisoPayload, 'versionBase'>): Promise<void> {
    if (!admin.value) return
    publicando.value = true
    try {
      admin.value = await privacidadService.publicar(admin.value, cambios)
      // La versión pública cambió: la siguiente consulta la vuelve a pedir.
      vigente.value = null
    } finally {
      publicando.value = false
    }
  }

  return {
    vigente,
    cargandoVigente,
    errorVigente,
    admin,
    cargandoAdmin,
    errorAdmin,
    publicando,
    cargarVigente,
    cargarAdmin,
    publicar,
  }
})
