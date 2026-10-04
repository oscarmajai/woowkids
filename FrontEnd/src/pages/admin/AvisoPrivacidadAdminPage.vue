<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Notify } from 'quasar'
import PageHeader from '@/components/ui/PageHeader.vue'
import BaseDialog from '@/components/ui/BaseDialog.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import { useAvisoPrivacidadStore } from '@/stores/avisoPrivacidad'
import { RUTA_AVISO_PRIVACIDAD } from '@/utils/avisoPrivacidad'
import type { ApiError } from '@/types/auth'
import type { ResponsableAviso, VersionAviso } from '@/types/privacidad'

/**
 * Administración del aviso de privacidad (solo AdministradorSistema): datos
 * del responsable, plazos de conservación y textos. Cada publicación es una
 * versión nueva; los registros de entrada siguientes deben aceptarla.
 */
const store = useAvisoPrivacidadStore()

const responsable = reactive<ResponsableAviso>({
  razonSocial: '',
  nombreComercial: '',
  domicilio: '',
  areaDatosPersonales: '',
  correoDatosPersonales: '',
  telefonoDatosPersonales: '',
  urlAviso: '',
  diasConservacionImagenes: 90,
  aniosConservacionRegistros: 5,
})
const textoIntegral = ref('')
const textoSimplificado = ref('')
const motivoCambio = ref('')
const pestana = ref<'integral' | 'simplificado'>('integral')
const confirmar = ref(false)

type CampoTexto = Exclude<
  keyof ResponsableAviso,
  'diasConservacionImagenes' | 'aniosConservacionRegistros'
>

const CAMPOS: { key: CampoTexto; label: string; hint?: string; full?: boolean }[] = [
  { key: 'razonSocial', label: 'Razón social', hint: 'Tal como aparece en el RFC' },
  { key: 'nombreComercial', label: 'Nombre comercial' },
  {
    key: 'domicilio',
    label: 'Domicilio',
    hint: 'Calle, número, colonia, CP, ciudad y estado',
    full: true,
  },
  {
    key: 'areaDatosPersonales',
    label: 'Persona o departamento de datos personales',
    hint: 'Quien atiende las solicitudes ARCO',
  },
  { key: 'correoDatosPersonales', label: 'Correo para derechos ARCO' },
  { key: 'telefonoDatosPersonales', label: 'Teléfono para derechos ARCO' },
]

function cargarFormulario(): void {
  const admin = store.admin
  if (!admin) return
  Object.assign(responsable, admin.responsable)
  textoIntegral.value = admin.textoIntegral
  textoSimplificado.value = admin.textoSimplificado
  motivoCambio.value = ''
}

watch(() => store.admin, cargarFormulario)

onMounted(() => {
  void store.cargarAdmin()
})

const hayCambios = computed(() => {
  const admin = store.admin
  if (!admin) return false
  const camposCambiados = (Object.keys(responsable) as (keyof ResponsableAviso)[]).some(
    (k) => responsable[k] !== admin.responsable[k],
  )
  return (
    camposCambiados ||
    textoIntegral.value !== admin.textoIntegral ||
    textoSimplificado.value !== admin.textoSimplificado
  )
})

const datosValidos = computed(
  () =>
    Number.isInteger(responsable.diasConservacionImagenes) &&
    responsable.diasConservacionImagenes >= 1 &&
    Number.isInteger(responsable.aniosConservacionRegistros) &&
    responsable.aniosConservacionRegistros >= 1 &&
    textoIntegral.value.trim().length > 0 &&
    textoSimplificado.value.trim().length > 0,
)

/** Se arma aquí porque en la plantilla las dobles llaves abren una interpolación. */
function marcadorTexto(nombre: string | number): string {
  return `{{${nombre}}}`
}

function usarDireccionDeEstaInstalacion(): void {
  responsable.urlAviso = `${window.location.origin}${RUTA_AVISO_PRIVACIDAD}`
}

function fecha(iso: string): string {
  return new Date(iso).toLocaleString('es-MX', { dateStyle: 'long', timeStyle: 'short' })
}

function metaVersion(v: VersionAviso): string {
  return [fecha(v.vigenteDesde), v.publicadoPor].filter(Boolean).join(' · ')
}

const subtitulo = computed(() => {
  const admin = store.admin
  if (!admin) return 'Datos del responsable y textos del aviso (LFPDPPP).'
  const quien = admin.publicadoPor ? ` · publicada por ${admin.publicadoPor}` : ''
  return `Versión ${admin.version} vigente desde el ${fecha(admin.vigenteDesde)}${quien}.`
})

async function publicar(): Promise<void> {
  try {
    await store.publicar({
      responsable: { ...responsable },
      textoIntegral: textoIntegral.value,
      textoSimplificado: textoSimplificado.value,
      motivoCambio: motivoCambio.value,
    })
    confirmar.value = false
    Notify.create({
      type: 'positive',
      message: `Se publicó la versión ${store.admin?.version} del aviso de privacidad.`,
      position: 'top-right',
    })
  } catch (err) {
    Notify.create({
      type: 'negative',
      message: (err as Partial<ApiError>)?.message || 'No se pudo publicar el aviso.',
      position: 'top-right',
    })
  }
}
</script>

<template>
  <q-page class="page-content list-page">
    <PageHeader title="Aviso de privacidad" :subtitle="subtitulo">
      <template #actions>
        <q-btn
          outline
          no-caps
          color="primary"
          icon="open_in_new"
          label="Ver aviso publicado"
          :href="RUTA_AVISO_PRIVACIDAD"
          target="_blank"
        />
        <q-btn
          unelevated
          no-caps
          color="primary"
          icon="publish"
          label="Publicar nueva versión"
          :disable="!hayCambios || !datosValidos"
          @click="confirmar = true"
        />
      </template>
    </PageHeader>

    <div class="list-page__note list-page__note--warn" role="note">
      <q-icon name="gavel" size="19px" />
      <span>
        El texto es una <b>plantilla</b>. Antes de usarlo con clientes, pide a un abogado que lo
        revise y lo adapte a tu negocio conforme a la Ley Federal de Protección de Datos Personales
        en Posesión de los Particulares (DOF 20-03-2025).
      </span>
    </div>

    <StateBlock
      v-if="store.errorAdmin"
      variant="error"
      :body="store.errorAdmin"
      action-label="Reintentar"
      @action="store.cargarAdmin()"
    />
    <div v-else-if="store.cargandoAdmin && !store.admin" class="aviso-admin__loading">
      <q-spinner color="primary" size="24px" />Cargando el aviso de privacidad…
    </div>

    <template v-else-if="store.admin">
      <div v-if="store.admin.pendientes.length" class="list-page__note list-page__note--bad">
        <q-icon name="error_outline" size="19px" />
        <span>
          Faltan datos del responsable: {{ store.admin.pendientes.join(', ') }}. En el aviso
          publicado aparecen como «Pendiente de configurar».
        </span>
      </div>

      <div class="aviso-admin">
        <div class="aviso-admin__main">
          <section class="aviso-card">
            <h2 class="aviso-card__title">Responsable de los datos</h2>
            <div class="form-grid">
              <label
                v-for="campo in CAMPOS"
                :key="campo.key"
                class="form-grid__field"
                :class="{ 'form-grid__field--full': campo.full }"
              >
                <span class="field-label">{{ campo.label }}</span>
                <q-input v-model.trim="responsable[campo.key]" outlined dense :hint="campo.hint" />
              </label>
              <label class="form-grid__field form-grid__field--full">
                <span class="field-label">Dirección web del aviso integral</span>
                <q-input
                  v-model.trim="responsable.urlAviso"
                  outlined
                  dense
                  placeholder="https://…/aviso-de-privacidad"
                  hint="Se cita en el aviso simplificado para consultar el integral"
                >
                  <template #after>
                    <q-btn
                      flat
                      dense
                      no-caps
                      color="primary"
                      label="Usar la de esta instalación"
                      @click="usarDireccionDeEstaInstalacion"
                    />
                  </template>
                </q-input>
              </label>
            </div>
          </section>

          <section class="aviso-card">
            <h2 class="aviso-card__title">Plazos de conservación</h2>
            <div class="form-grid">
              <label class="form-grid__field">
                <span class="field-label">INE, fotografías y notas de salud</span>
                <q-input
                  v-model.number="responsable.diasConservacionImagenes"
                  outlined
                  dense
                  type="number"
                  min="1"
                  max="3650"
                  step="1"
                  suffix="días"
                  hint="Después de la visita"
                />
              </label>
              <label class="form-grid__field">
                <span class="field-label">Registros de visitas, cobros y eventos</span>
                <q-input
                  v-model.number="responsable.aniosConservacionRegistros"
                  outlined
                  dense
                  type="number"
                  min="1"
                  max="20"
                  step="1"
                  suffix="años"
                  hint="Obligaciones fiscales y aclaraciones"
                />
              </label>
            </div>
            <p class="aviso-card__hint">
              El sistema todavía no borra estos datos al vencer el plazo: hay que depurarlos a mano
              o con un proceso programado.
            </p>
          </section>

          <section class="aviso-card">
            <div class="aviso-card__head">
              <h2 class="aviso-card__title">Texto del aviso</h2>
              <q-btn-toggle
                v-model="pestana"
                no-caps
                unelevated
                toggle-color="primary"
                :options="[
                  { label: 'Integral', value: 'integral' },
                  { label: 'Simplificado', value: 'simplificado' },
                ]"
              />
            </div>
            <q-input
              v-if="pestana === 'integral'"
              v-model="textoIntegral"
              outlined
              type="textarea"
              autogrow
              class="aviso-card__texto"
              aria-label="Texto del aviso integral"
            />
            <q-input
              v-else
              v-model="textoSimplificado"
              outlined
              type="textarea"
              autogrow
              class="aviso-card__texto"
              aria-label="Texto del aviso simplificado"
            />
            <p class="aviso-card__hint">
              Formato: «# » título, «## » sección, «- » viñeta; deja una línea en blanco entre
              párrafos.
            </p>
          </section>
        </div>

        <aside class="aviso-admin__aside">
          <section class="aviso-card">
            <h2 class="aviso-card__title">Marcadores</h2>
            <p class="aviso-card__hint">Se reemplazan al publicar con los datos de la izquierda.</p>
            <dl class="aviso-marcadores">
              <template v-for="(label, marcador) in store.admin.marcadores" :key="marcador">
                <dt>
                  <code>{{ marcadorTexto(marcador) }}</code>
                </dt>
                <dd>{{ label }}</dd>
              </template>
            </dl>
          </section>

          <section class="aviso-card">
            <h2 class="aviso-card__title">Versiones publicadas</h2>
            <ol class="aviso-historial">
              <li v-for="v in store.admin.historial" :key="v.version">
                <span class="aviso-historial__version">Versión {{ v.version }}</span>
                <span class="aviso-historial__meta">{{ metaVersion(v) }}</span>
                <span v-if="v.motivoCambio" class="aviso-historial__motivo">
                  {{ v.motivoCambio }}
                </span>
              </li>
            </ol>
          </section>
        </aside>
      </div>
    </template>

    <BaseDialog
      v-model="confirmar"
      title="Publicar nueva versión"
      :subtitle="store.admin ? `Versión ${store.admin.version + 1}` : undefined"
      icon="publish"
      tone="amber"
      primary-label="Publicar"
      :loading="store.publicando"
      @confirm="publicar"
    >
      <p class="aviso-confirmar">
        A partir de ahora, cada registro de entrada deberá aceptar esta versión. Las versiones
        anteriores se conservan para demostrar qué aceptó cada tutor.
      </p>
      <label class="form-grid__field">
        <span class="field-label">Motivo del cambio (opcional)</span>
        <q-input v-model="motivoCambio" outlined dense maxlength="500" />
      </label>
    </BaseDialog>
  </q-page>
</template>

<style scoped lang="scss">
.aviso-admin {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 18px;
  align-items: start;

  @media (max-width: 1100px) {
    grid-template-columns: minmax(0, 1fr);
  }

  &__main,
  &__aside {
    display: flex;
    flex-direction: column;
    gap: 18px;
    min-width: 0;
  }

  &__loading {
    display: flex;
    align-items: center;
    gap: 12px;
    color: var(--text-secondary);
    font-weight: 600;
  }
}

.aviso-card {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;

  &__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  &__title {
    margin: 0;
    font-size: 15px;
    line-height: 1.3;
    font-weight: 800;
    color: var(--text-strong);
  }

  &__hint {
    margin: 0;
    font-size: 12.5px;
    color: var(--text-secondary);
  }

  &__texto :deep(textarea) {
    font-family: ui-monospace, Menlo, monospace;
    font-size: 13px;
    line-height: 1.55;
  }
}

.aviso-marcadores {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12.5px;

  dt code {
    font-size: 12px;
    color: var(--text-strong);
  }

  dd {
    margin: 0 0 4px;
    color: var(--text-secondary);
  }
}

.aviso-historial {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;

  li {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  &__version {
    font-weight: 800;
    color: var(--text-strong);
  }

  &__meta,
  &__motivo {
    font-size: 12.5px;
    color: var(--text-secondary);
  }
}

.aviso-confirmar {
  margin: 0 0 14px;
  font-size: 14px;
  color: var(--text-body);
}
</style>
