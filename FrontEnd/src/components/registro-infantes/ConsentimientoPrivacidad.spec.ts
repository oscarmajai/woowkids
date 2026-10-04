import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it } from 'vitest'
import { defineComponent, h } from 'vue'

import ConsentimientoPrivacidad from './ConsentimientoPrivacidad.vue'
import { useRegistrationStore } from '@/stores/registration'

// Diálogo sin teleport: pinta su contenido cuando está abierto y un botón
// que emite la acción primaria.
const BaseDialogStub = defineComponent({
  props: { modelValue: Boolean, primaryLabel: { type: String, default: '' } },
  emits: ['confirm', 'update:modelValue'],
  setup(props, { slots, emit }) {
    return () =>
      props.modelValue
        ? h('div', { class: 'dialogo' }, [
            slots.default?.(),
            h(
              'button',
              { class: 'dialogo__ok', onClick: () => emit('confirm') },
              props.primaryLabel,
            ),
          ])
        : null
  },
})

function montar() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useRegistrationStore()
  store.avisoPrivacidad = {
    version: 3,
    vigenteDesde: '2026-10-03T18:00:00Z',
    fechaVigencia: '2026-10-03',
    nombreComercial: 'Woow Kids',
    textoIntegral: '# Integral',
    textoSimplificado:
      '# AVISO DE PRIVACIDAD SIMPLIFICADO\n\nUsamos sus datos para cuidar a los niños.',
  }
  const wrapper = mount(ConsentimientoPrivacidad, {
    global: { plugins: [pinia], stubs: { BaseDialog: BaseDialogStub } },
  })
  return { wrapper, store }
}

describe('ConsentimientoPrivacidad', () => {
  it('pide la aceptación del tutor y ofrece negarse a las finalidades voluntarias', () => {
    const { wrapper } = montar()

    expect(wrapper.text()).toContain('El tutor leyó y acepta el aviso de privacidad')
    expect(wrapper.text()).toContain('NO desea que sus datos se usen para el programa de lealtad')
    expect(wrapper.text()).toContain('versión 3')
    expect(wrapper.text()).not.toContain('Aceptado')
  })

  it('la casilla marca la aceptación en el store', async () => {
    const { wrapper, store } = montar()

    await wrapper.findAll('.q-checkbox')[0].trigger('click')

    expect(store.aceptaAvisoPrivacidad).toBe(true)
    expect(store.avisoAceptado).toBe(true)
    expect(wrapper.text()).toContain('Aceptado')
  })

  it('muestra el aviso simplificado con enlace al integral y permite aceptarlo ahí', async () => {
    const { wrapper, store } = montar()
    const ver = wrapper.findAll('button').find((b) => b.text().includes('Ver aviso'))
    await ver!.trigger('click')

    expect(wrapper.find('.dialogo').text()).toContain('Usamos sus datos para cuidar a los niños.')
    const integral = wrapper.find('a[href="/aviso-de-privacidad"]')
    expect(integral.exists()).toBe(true)
    expect(integral.attributes('target')).toBe('_blank')

    await wrapper.find('.dialogo__ok').trigger('click')
    expect(store.aceptaAvisoPrivacidad).toBe(true)
  })

  it('negarse a lealtad avisa que no habrá puntos', async () => {
    const { wrapper, store } = montar()

    await wrapper.findAll('.q-checkbox')[1].trigger('click')

    expect(store.rechazaFinalidadesSecundarias).toBe(true)
    expect(wrapper.text()).toContain('no acumulará ni canjeará puntos')
  })
})
