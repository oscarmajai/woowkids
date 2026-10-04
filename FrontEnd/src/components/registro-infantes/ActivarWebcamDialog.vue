<script setup lang="ts">
import { computed, ref } from 'vue'
import BaseDialog from '@/components/ui/BaseDialog.vue'
import { descargarActivador, esWindows } from '@/utils/activarWebcam'

/**
 * Se abre solo en una computadora que entra por HTTP desde la red local: ahí
 * el navegador no ofrece la webcam (ver utils/activarWebcam.ts). En Windows
 * descarga el activador; en otros sistemas explica el ajuste de Chrome.
 */
const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ 'usar-archivo': [] }>()

const windows = esWindows()
const descargado = ref(false)
const origen = window.location.origin
const paginaRegistro = `${origen}/estancias/registro-infantes`
const banderaChrome = 'chrome://flags/#unsafely-treat-insecure-origin-as-secure'

const subtitulo = computed(() =>
  descargado.value ? 'Abre el archivo descargado' : 'Una sola vez en esta computadora',
)

function activar(): void {
  descargarActivador(paginaRegistro, origen)
  descargado.value = true
}

function usarArchivo(): void {
  open.value = false
  emit('usar-archivo')
}
</script>

<template>
  <BaseDialog
    v-model="open"
    title="Activar la webcam en esta computadora"
    :subtitle="subtitulo"
    icon="videocam"
    :width="520"
  >
    <div class="activar-webcam">
      <p>
        Para tomar las fotos de INE y de llegada con la webcam, el navegador necesita que la actives
        una vez en esta computadora. Después, al tomar la foto, solo da
        <strong>Permitir</strong>.
      </p>

      <template v-if="windows">
        <ol v-if="descargado" class="activar-webcam__pasos">
          <li>
            Abre <strong>activar-webcam-woowkids.cmd</strong> desde las descargas del navegador (si
            pregunta, elige <strong>Conservar</strong> o <strong>Ejecutar</strong>).
          </li>
          <li>Windows pedirá permiso: elige <strong>Sí</strong>.</li>
          <li>
            El navegador se cierra y se vuelve a abrir solo en el registro de entrada. Al tomar la
            foto, elige <strong>Permitir</strong>.
          </li>
        </ol>
        <p v-else class="activar-webcam__nota">
          El navegador se reiniciará: haz esto antes de capturar el registro.
        </p>
      </template>

      <ol v-else class="activar-webcam__pasos">
        <li>
          En Chrome abre <code>{{ banderaChrome }}</code
          >.
        </li>
        <li>
          En «Insecure origins treated as secure» escribe <code>{{ origen }}</code> y elige
          <strong>Enabled</strong>.
        </li>
        <li>Pulsa <strong>Relaunch</strong> y vuelve al registro.</li>
      </ol>
    </div>

    <template #footer>
      <q-btn flat color="grey-8" label="Ahora no, usar un archivo" @click="usarArchivo" />
      <q-btn
        v-if="windows"
        unelevated
        color="primary"
        icon="download"
        :label="descargado ? 'Descargar de nuevo' : 'Activar'"
        @click="activar"
      />
    </template>
  </BaseDialog>
</template>

<style scoped lang="scss">
.activar-webcam {
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 14px;
  line-height: 1.55;
  color: var(--text-secondary);

  p {
    margin: 0;
  }

  &__pasos {
    margin: 0;
    padding-left: 20px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  &__nota {
    color: var(--tone-warn-fg);
    font-weight: 600;
  }

  code {
    word-break: break-all;
    font-size: 12.5px;
  }
}
</style>
