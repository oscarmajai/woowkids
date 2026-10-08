import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

/** "¿Olvidaste tu contraseña?" explica qué hacer (no hay recuperación por correo). */

vi.mock('@/composables/useAuthForm', () => ({
  useAuthForm: () => ({
    credentials: ref({ email: '', password: '', rememberMe: false }),
    showPassword: ref(false),
    emailRules: [],
    passwordRules: [],
    isLoading: () => false,
    pendingBranchSelection: () => null,
    handleLogin: vi.fn(),
    confirmBranchSelection: vi.fn(),
    cancelBranchSelection: vi.fn(),
  }),
}))

const { default: LoginPage } = await import('@/pages/auth/LoginPage.vue')

describe('LoginPage', () => {
  it('"¿Olvidaste tu contraseña?" explica a quién pedir una contraseña nueva', async () => {
    const wrapper = mount(LoginPage, {
      attachTo: document.body,
      global: { stubs: { QPage: { template: '<div><slot /></div>' } } },
    })
    expect(document.body.textContent).not.toContain('Pide a tu administrador')

    await wrapper.find('.auth-forgot').trigger('click')
    await flushPromises()

    expect(document.body.textContent).toContain(
      'Pide a tu administrador que te asigne una contraseña nueva desde Usuarios',
    )
    wrapper.unmount()
  })
})
