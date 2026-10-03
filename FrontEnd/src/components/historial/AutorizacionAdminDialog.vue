<template>
  <q-dialog ref="dialogRef" persistent @hide="onDialogHide">
    <q-card class="autoriza">
      <header class="autoriza__head">
        <span class="autoriza__icon"><q-icon name="admin_panel_settings" size="22px" /></span>
        <div class="autoriza__titles">
          <span class="autoriza__title">Autorización de administrador</span>
          <span class="autoriza__subtitle">
            {{
              mensaje ||
              'La orden ya está pagada: cancelarla requiere el PIN de un administrador de la sucursal.'
            }}
          </span>
        </div>
      </header>

      <div class="autoriza__body">
        <label class="autoriza__field">
          <span class="field-label">Correo del administrador</span>
          <q-input
            v-model="email"
            type="email"
            outlined
            dense
            autofocus
            autocomplete="off"
            aria-label="Correo del administrador"
            :disable="validando"
          />
        </label>
        <label class="autoriza__field">
          <span class="field-label">PIN</span>
          <q-input
            v-model="pin"
            type="password"
            maxlength="4"
            outlined
            dense
            placeholder="••••"
            autocomplete="off"
            aria-label="PIN del administrador"
            :disable="validando"
            @keydown="filtrarTeclaEntero"
            @keyup.enter="confirmar"
          />
        </label>
        <p class="autoriza__hint">
          La devolución al cliente se registrará en tu turno de caja: la parte en efectivo se resta
          del efectivo esperado del arqueo.
        </p>
        <p v-if="error" class="autoriza__error" role="alert">{{ error }}</p>
      </div>

      <footer class="autoriza__foot">
        <q-btn outline label="Volver" :disable="validando" @click="onDialogCancel" />
        <q-btn
          unelevated
          color="negative"
          label="Autorizar cancelación"
          :loading="validando"
          :disable="!puedeConfirmar"
          @click="confirmar"
        />
      </footer>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useDialogPluginComponent } from 'quasar'
import { turnoCajaService } from '@/services/turnoCajaService'
import { mensajeDeError } from '@/utils/errorHandler'
import { filtrarTeclaEntero } from '@/utils/validacionNumerica'

const props = defineProps<{
  turnoId: string
  mensaje?: string
}>()

defineEmits([...useDialogPluginComponent.emits])

const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } = useDialogPluginComponent()

const email = ref('')
const pin = ref('')
const validando = ref(false)
const error = ref<string | null>(null)

const puedeConfirmar = computed(() => !!email.value.trim() && pin.value.length === 4)

async function confirmar() {
  if (!puedeConfirmar.value || validando.value) return
  validando.value = true
  error.value = null
  try {
    const { ok, tokenPin } = await turnoCajaService.validarPinAdmin(
      props.turnoId,
      email.value.trim(),
      pin.value,
    )
    if (!ok || !tokenPin) {
      error.value = 'No se pudo validar el PIN del administrador.'
      return
    }
    onDialogOK(tokenPin)
  } catch (err) {
    pin.value = ''
    error.value = mensajeDeError(err, 'El PIN del administrador es incorrecto.')
  } finally {
    validando.value = false
  }
}
</script>

<style scoped lang="scss">
.autoriza {
  width: 440px;
  max-width: 96vw;

  &__head {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    padding: 22px 24px 18px;
    border-bottom: 1px solid var(--border-soft);
  }

  &__icon {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    background: var(--tone-bad-bg);
    color: var(--tone-bad-fg);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  &__titles {
    display: flex;
    flex-direction: column;
    gap: 3px;
    flex: 1;
  }

  &__title {
    font-size: 18px;
    font-weight: 800;
    color: var(--text-strong);
  }

  &__subtitle {
    font-size: 13px;
    color: var(--text-muted);
  }

  &__body {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 18px 24px;
  }

  &__field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  &__hint {
    margin: 0;
    font-size: 12.5px;
    color: var(--text-muted);
  }

  &__error {
    margin: 0;
    font-size: 13px;
    font-weight: 600;
    color: var(--tone-bad-fg);
  }

  &__foot {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 14px 24px 20px;
    border-top: 1px solid var(--border-soft);
  }
}
</style>
