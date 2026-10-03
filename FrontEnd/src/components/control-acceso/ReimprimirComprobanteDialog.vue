<template>
  <BaseDialog
    v-model="open"
    title="Reimprimir comprobante"
    :subtitle="subtitulo"
    icon="print"
    :width="460"
    :loading="cargando"
    :primary-label="datos ? 'Imprimir' : 'Generar e imprimir'"
    secondary-label="Cerrar"
    @confirm="onConfirmar"
    @cancel="limpiar"
  >
    <div v-if="!datos" class="reprint__note">
      <q-icon name="qr_code_2" size="20px" />
      <span>
        Se genera un QR nuevo para el portal de padres; el del comprobante anterior deja de
        funcionar.
      </span>
    </div>
    <div v-if="error" class="reprint__note reprint__note--bad" role="alert">
      <q-icon name="error" size="20px" />
      <span>{{ error }}</span>
    </div>
    <div v-if="datos" class="reprint__ticket">
      <ComprobanteEstancia ref="ticketRef" :datos="datos" />
    </div>
  </BaseDialog>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import BaseDialog from '@/components/ui/BaseDialog.vue'
import ComprobanteEstancia from '@/components/registro-infantes/ComprobanteEstancia.vue'
import { reimprimirComprobanteEstancia } from '@/services/comprobanteEstanciaService'
import type { DatosComprobanteEstancia } from '@/types/comprobanteEstancia'
import { mensajeDeError } from '@/utils/errorHandler'
import { printTicketElement } from '@/utils/ticketPrinting'

/**
 * N5: reimpresión del comprobante de entrada desde Control de Acceso. El
 * código nuevo se pide hasta que el cajero confirma (pedirlo revoca el QR
 * anterior), y después el mismo diálogo permite volver a imprimir.
 */
const props = defineProps<{ registroId: string; subtitulo?: string }>()
const open = defineModel<boolean>({ required: true })

const datos = ref<DatosComprobanteEstancia | null>(null)
const cargando = ref(false)
const error = ref<string | null>(null)
const ticketRef = ref<InstanceType<typeof ComprobanteEstancia> | null>(null)

async function onConfirmar(): Promise<void> {
  cargando.value = true
  error.value = null
  try {
    if (!datos.value) {
      datos.value = await reimprimirComprobanteEstancia(props.registroId)
      await nextTick()
    }
    await printTicketElement(ticketRef.value?.raiz ?? null)
  } catch (err) {
    error.value = mensajeDeError(err, 'No se pudo reimprimir el comprobante.')
  } finally {
    cargando.value = false
  }
}

function limpiar(): void {
  datos.value = null
  error.value = null
}
</script>

<style scoped lang="scss">
.reprint {
  &__note {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--tone-info-bg);
    color: var(--tone-info-fg);
    font-size: 13px;
    font-weight: 600;
    line-height: 1.45;

    &--bad {
      margin-top: 10px;
      background: var(--tone-bad-bg);
      color: var(--tone-bad-fg);
    }
  }

  &__ticket {
    display: flex;
    justify-content: center;
    margin-top: 12px;
  }
}
</style>
