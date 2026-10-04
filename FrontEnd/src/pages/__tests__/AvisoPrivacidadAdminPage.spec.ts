import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, type Slots } from 'vue'

import AvisoPrivacidadAdminPage from '@/pages/admin/AvisoPrivacidadAdminPage.vue'
import { privacidadService } from '@/services/privacidadService'
import type { AvisoPrivacidadAdmin } from '@/types/privacidad'

const notify = vi.fn()
vi.mock('quasar', async (original) => {
  const real = await original<typeof import('quasar')>()
  return { ...real, Notify: { ...real.Notify, create: (...a: unknown[]) => notify(...a) } }
})

vi.mock('@/services/privacidadService', () => ({
  privacidadService: { obtenerAdmin: vi.fn(), publicar: vi.fn() },
}))

// QPage exige un QLayout padre: aquí basta con pintar su contenido.
const QPageStub = {
  setup(_: unknown, { slots }: { slots: Slots }) {
    return () => h('div', slots.default?.())
  },
}

const BaseDialogStub = defineComponent({
  props: { modelValue: Boolean },
  emits: ['confirm', 'update:modelValue'],
  setup(props, { slots, emit }) {
    return () =>
      props.modelValue
        ? h('div', { class: 'dialogo' }, [
            slots.default?.(),
            h('button', { class: 'dialogo__ok', onClick: () => emit('confirm') }, 'Publicar'),
          ])
        : null
  },
})

function admin(cambios: Partial<AvisoPrivacidadAdmin> = {}): AvisoPrivacidadAdmin {
  return {
    version: 1,
    vigenteDesde: '2026-10-03T18:00:00Z',
    publicadoPor: null,
    motivoCambio: 'Plantilla inicial',
    responsable: {
      razonSocial: '',
      nombreComercial: 'Woow Kids',
      domicilio: '',
      areaDatosPersonales: 'Departamento de Datos Personales',
      correoDatosPersonales: '',
      telefonoDatosPersonales: '',
      urlAviso: '',
      diasConservacionImagenes: 90,
      aniosConservacionRegistros: 5,
    },
    textoIntegral: '# AVISO INTEGRAL\n\n{{razon_social}}',
    textoSimplificado: '# AVISO SIMPLIFICADO',
    marcadores: { razon_social: 'Razón social', domicilio: 'Domicilio' },
    pendientes: ['Razón social', 'Domicilio'],
    historial: [
      {
        version: 1,
        vigenteDesde: '2026-10-03T18:00:00Z',
        publicadoPor: null,
        motivoCambio: 'Plantilla inicial',
      },
    ],
    ...cambios,
  }
}

async function montar() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const wrapper = mount(AvisoPrivacidadAdminPage, {
    global: { plugins: [pinia], stubs: { QPage: QPageStub, BaseDialog: BaseDialogStub } },
  })
  await flushPromises()
  return wrapper
}

function botonPublicar(wrapper: Awaited<ReturnType<typeof montar>>) {
  return wrapper.findAll('button').find((b) => b.text().includes('Publicar nueva versión'))!
}

describe('AvisoPrivacidadAdminPage', () => {
  beforeEach(() => {
    notify.mockReset()
    vi.mocked(privacidadService.obtenerAdmin).mockReset().mockResolvedValue(admin())
    vi.mocked(privacidadService.publicar).mockReset()
  })

  it('advierte que el texto es una plantilla que debe revisar un abogado', async () => {
    const wrapper = await montar()

    expect(wrapper.text()).toContain('El texto es una plantilla')
    expect(wrapper.text()).toContain('pide a un abogado que lo revise')
  })

  it('muestra los datos del responsable que faltan y los marcadores', async () => {
    const wrapper = await montar()

    expect(wrapper.text()).toContain('Faltan datos del responsable: Razón social, Domicilio')
    expect(wrapper.text()).toContain('{{razon_social}}')
    expect(wrapper.text()).toContain('Versión 1')
  })

  it('sin cambios no deja publicar', async () => {
    const wrapper = await montar()

    expect(botonPublicar(wrapper).attributes('disabled')).toBeDefined()
  })

  it('publica los datos del responsable capturados', async () => {
    vi.mocked(privacidadService.publicar).mockResolvedValue(
      admin({ version: 2, pendientes: ['Domicilio'] }),
    )
    const wrapper = await montar()

    const razonSocial = wrapper.findAll('input')[0]
    await razonSocial.setValue('Diversión Infantil SA de CV')
    expect(botonPublicar(wrapper).attributes('disabled')).toBeUndefined()

    await botonPublicar(wrapper).trigger('click')
    await wrapper.find('.dialogo__ok').trigger('click')
    await flushPromises()

    expect(privacidadService.publicar).toHaveBeenCalledTimes(1)
    const [actual, cambios] = vi.mocked(privacidadService.publicar).mock.calls[0]
    expect(actual.version).toBe(1)
    expect(cambios.responsable.razonSocial).toBe('Diversión Infantil SA de CV')
    expect(cambios.textoIntegral).toBe('# AVISO INTEGRAL\n\n{{razon_social}}')
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'positive', message: expect.stringContaining('versión 2') }),
    )
  })

  it('si alguien publicó otra versión, muestra el mensaje del backend', async () => {
    vi.mocked(privacidadService.publicar).mockRejectedValue({
      statusCode: 409,
      code: 'CONFLICT',
      message: 'Mientras editabas se publicó la versión 2 del aviso.',
    })
    const wrapper = await montar()

    await wrapper.findAll('input')[0].setValue('Otra SA')
    await botonPublicar(wrapper).trigger('click')
    await wrapper.find('.dialogo__ok').trigger('click')
    await flushPromises()

    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'negative',
        message: 'Mientras editabas se publicó la versión 2 del aviso.',
      }),
    )
  })
})
