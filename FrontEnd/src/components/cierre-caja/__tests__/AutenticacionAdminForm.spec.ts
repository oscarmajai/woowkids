import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

import AutenticacionAdminForm from '@/components/cierre-caja/AutenticacionAdminForm.vue'
import BaseDialog from '@/components/ui/BaseDialog.vue'

/**
 * UX caja: el "Cancelar" del diálogo "Autorización de administrador" llamaba a
 * cancelarConteo() y tiraba todo el conteo enviado. Ahora solo cierra el
 * diálogo; el aviso de espera sigue ofreciendo "Cancelar y corregir conteo".
 */

const turno = reactive({
  mostrarDialogAdmin: true,
  credencialesAdmin: { email: '', password: '', error: '', cargando: false },
  cancelarConteo: vi.fn(),
  autenticarAdmin: vi.fn(),
})
vi.mock('@/stores/turnoCaja', () => ({ useTurnoCajaStore: () => turno }))

describe('AutenticacionAdminForm', () => {
  it('Cancelar solo cierra el diálogo, no cancela el conteo', async () => {
    const wrapper = shallowMount(AutenticacionAdminForm)

    wrapper.findComponent(BaseDialog).vm.$emit('cancel')
    await wrapper.vm.$nextTick()

    expect(turno.mostrarDialogAdmin).toBe(false)
    expect(turno.cancelarConteo).not.toHaveBeenCalled()
  })
})
