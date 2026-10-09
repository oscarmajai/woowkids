<template>
  <div id="printable-voucher" ref="raiz" class="voucher">
    <!-- Encabezado -->
    <div class="text-center">
      <TicketLogo :ancho-mm="80" />
      <div class="ticket-sub">{{ datos.sucursal }}</div>
      <div class="ticket-sub">Cajero: {{ datos.cajero }}</div>
      <div v-if="datos.reimpresion" class="ticket-reprint">REIMPRESIÓN</div>
    </div>

    <div class="ticket-divider">--------------------------------</div>

    <!-- Fecha y Tutor Compactos -->
    <div class="ticket-row">
      <span>{{ datos.reimpresion ? 'Entrada:' : 'Fecha:' }}</span>
      <span class="text-weight-bold">{{ fecha }}</span>
    </div>
    <div class="ticket-row">
      <span>Tutor:</span>
      <span class="text-ellipsis">{{ datos.tutor }}</span>
    </div>
    <div v-if="datos.telefono" class="ticket-row">
      <span>Tel:</span>
      <span>{{ datos.telefono }}</span>
    </div>

    <div class="ticket-divider">--------------------------------</div>

    <!-- Niños Registrados -->
    <div class="ticket-section-title">NIÑOS REGISTRADOS</div>
    <template v-for="(nino, i) in datos.ninos" :key="i">
      <div class="ticket-row items-center q-my-xs">
        <span class="text-weight-bold text-ellipsis">{{ nino.nombre }}</span>
        <span>{{ nino.edad }} años</span>
      </div>
      <!-- Las notas / alergias salen en el comprobante. -->
      <div v-if="notaVisible(nino.notas)" class="ticket-notes">
        * Notas / alergias: {{ notaVisible(nino.notas) }}
      </div>
    </template>

    <div class="ticket-divider">--------------------------------</div>

    <!-- Salida y Pago -->
    <div class="ticket-box q-my-xs text-center">
      Salida Estimada: <strong>{{ datos.salidaEstimada }}</strong>
    </div>

    <div class="ticket-row text-weight-bold q-mt-xs" style="font-size: 13px">
      <span>TOTAL:</span>
      <span>${{ Number(datos.total).toFixed(2) }}</span>
    </div>

    <!-- QR -->
    <div v-if="datos.qrCodeUrl" class="text-center q-mt-sm">
      <img :src="datos.qrCodeUrl" alt="QR" class="qr-code" />
      <div class="ticket-caption">Escanea para ver tu registro</div>
    </div>

    <div class="text-center ticket-footer q-mt-xs">¡Gracias por visitarnos!</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { DatosComprobanteEstancia } from '@/types/comprobanteEstancia'
import { notaVisible } from '@/utils/notasNino'
import TicketLogo from '@/components/shared/TicketLogo.vue'

/**
 * Ticket del comprobante de entrada de estancias. Solo pinta: lo usan el
 * registro completado (PrintVoucher) y la reimpresión desde Control de Acceso.
 * `raiz` se expone para imprimirlo con printTicketElement.
 */
const props = defineProps<{ datos: DatosComprobanteEstancia }>()

const raiz = ref<HTMLElement | null>(null)
defineExpose({ raiz })

const fecha = computed(
  () =>
    props.datos.fecha.toLocaleDateString('es-MX', {
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
    }) +
    ' ' +
    props.datos.fecha.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' }),
)
</script>

<style scoped lang="scss">
/* Vista en pantalla del comprobante — el layout de impresión es universal (ver useTicketPrint/printTicketElement) */
.voucher {
  background: #fff;
  border-radius: 8px;
  padding: 14px 10px;
  width: 80mm;
  max-width: none;
  flex: none;
  box-sizing: border-box;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  font-family: 'Courier New', Courier, monospace;
  color: #000;
  font-size: 11px;
  line-height: 1.25;
}

.ticket-sub {
  font-size: 10px;
  color: #444;
}

.ticket-reprint {
  margin-top: 2px;
  font-size: 10px;
  font-weight: bold;
  letter-spacing: 1px;
}

.ticket-divider {
  text-align: center;
  overflow: hidden;
  white-space: nowrap;
  letter-spacing: -1px;
  color: #666;
  margin: 4px 0;
}

.ticket-section-title {
  font-size: 10px;
  font-weight: bold;
  text-align: center;
  margin-bottom: 2px;
}

.ticket-row {
  display: flex;
  justify-content: space-between;
  gap: 4px;
}

.text-ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ticket-notes {
  font-size: 10px;
  font-weight: bold;
  margin: -2px 0 4px;
  word-break: break-word;
}

.ticket-box {
  border: 1px dashed #000;
  padding: 4px;
  font-size: 11px;
}

.qr-code {
  width: 95px;
  height: 95px;
  display: inline-block;
}

.ticket-caption {
  font-size: 9px;
  color: #555;
  margin-top: 2px;
}

.ticket-footer {
  font-size: 10px;
}
</style>
