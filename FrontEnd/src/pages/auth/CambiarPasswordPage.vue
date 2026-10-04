<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { Notify } from 'quasar'
import type { QForm } from 'quasar'
import { useRoute, useRouter } from 'vue-router'
import { userService } from '@/services/userService'
import { useAuthStore } from '@/stores/auth'
import { mensajeDeError } from '@/utils/errorHandler'

// El backend exige al menos 8 caracteres (PASSWORD_MIN_LENGTH en schemas/user.py).
const MIN_LENGTH = 8

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const formRef = ref<InstanceType<typeof QForm> | null>(null)
const form = reactive({ actual: '', nueva: '', confirmacion: '' })
const mostrar = ref(false)
const guardando = ref(false)

const obligatorio = computed(() => auth.currentUser?.debeCambiarPassword ?? false)

const reglasActual = [(v: string) => !!v || 'Escribe tu contraseña actual.']
const reglasNueva = [
  (v: string) => v.length >= MIN_LENGTH || `Debe tener al menos ${MIN_LENGTH} caracteres.`,
  (v: string) => v !== form.actual || 'Debe ser distinta a la actual.',
]
const reglasConfirmacion = [(v: string) => v === form.nueva || 'Las contraseñas no coinciden.']

async function onSubmit(): Promise<void> {
  const valid = await formRef.value?.validate()
  if (!valid) return
  guardando.value = true
  try {
    await userService.cambiarMiPassword(form.actual, form.nueva)
    auth.marcarPasswordCambiada()
    Notify.create({ type: 'positive', message: 'Contraseña actualizada.', icon: 'check_circle' })
    const redirect = route.query.redirect as string | undefined
    await router.push(redirect ?? { name: 'home' })
  } catch (err) {
    Notify.create({
      type: 'negative',
      message: mensajeDeError(err, 'No se pudo cambiar la contraseña.'),
      icon: 'error',
    })
  } finally {
    guardando.value = false
  }
}

async function salir(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <q-page class="cambio-page">
    <main class="cambio-main">
      <header class="cambio-head">
        <q-icon name="lock_reset" size="40px" class="cambio-icon" />
        <h1 class="cambio-title">Cambia tu contraseña</h1>
        <p v-if="obligatorio" class="cambio-subtitle">
          Por seguridad, antes de continuar elige una contraseña nueva. La que usaste es la de
          fábrica y cualquiera que conozca el sistema podría entrar con ella.
        </p>
        <p v-else class="cambio-subtitle">Elige una contraseña nueva para tu cuenta.</p>
      </header>

      <q-form ref="formRef" class="cambio-form" greedy @submit.prevent="onSubmit">
        <q-input
          v-model="form.actual"
          :type="mostrar ? 'text' : 'password'"
          label="Contraseña actual"
          outlined
          autocomplete="current-password"
          :rules="reglasActual"
          lazy-rules
          :disable="guardando"
        />
        <q-input
          v-model="form.nueva"
          :type="mostrar ? 'text' : 'password'"
          label="Contraseña nueva"
          outlined
          autocomplete="new-password"
          :rules="reglasNueva"
          lazy-rules
          :disable="guardando"
          :hint="`Al menos ${MIN_LENGTH} caracteres.`"
        />
        <q-input
          v-model="form.confirmacion"
          :type="mostrar ? 'text' : 'password'"
          label="Confirma la contraseña nueva"
          outlined
          autocomplete="new-password"
          :rules="reglasConfirmacion"
          lazy-rules
          :disable="guardando"
        />
        <q-checkbox v-model="mostrar" label="Mostrar contraseñas" dense />

        <q-btn
          type="submit"
          label="Guardar contraseña"
          color="primary"
          unelevated
          class="full-width cambio-submit"
          :loading="guardando"
        />
        <q-btn
          v-if="obligatorio"
          flat
          color="grey-8"
          label="Salir"
          class="full-width"
          :disable="guardando"
          @click="salir"
        />
        <q-btn
          v-else
          flat
          color="grey-8"
          label="Cancelar"
          class="full-width"
          :disable="guardando"
          @click="router.back()"
        />
      </q-form>
    </main>
  </q-page>
</template>

<style scoped lang="scss">
.cambio-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100% !important;
  overflow-y: auto;
  background: #fff;
}

.cambio-main {
  width: 100%;
  max-width: 420px;
  padding: 48px 16px;
}

.cambio-head {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 24px;
}

.cambio-icon {
  color: var(--q-primary);
}

.cambio-title {
  margin: 0;
  font-size: 26px;
  line-height: 1.2;
  font-weight: 800;
  color: var(--text-strong);
}

.cambio-subtitle {
  margin: 0;
  font-size: 14.5px;
  line-height: 1.5;
  color: var(--text-secondary);
}

.cambio-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.cambio-submit {
  height: 48px;
  border-radius: 12px;
  margin-top: 8px;
}
</style>
