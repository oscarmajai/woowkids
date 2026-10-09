<script setup lang="ts">
/**
 * Comprobante imprimible de un pago registrado sobre una reservación
 * (abono/liquidación desde Pagos o Cierre de Evento).
 *
 * Mismo lenguaje visual que TicketReservacion.vue, pero con clases propias en
 * el bloque de impresión sin `scoped`: reutilizar los nombres de ese
 * componente haría que ambas hojas de impresión (inyectadas globalmente por
 * Vue sin importar cuál esté montada) se pisaran entre sí.
 *
 * Se imprime con printTicketElement: toma el ancho del papel de la impresora
 * (58 u 80 mm) en vez de fijarlo.
 */

import { ref } from 'vue'
import { useQuasar } from 'quasar'
import type { TicketPagoEventoProps } from '@/types/ticketPagoEvento'

import { avisoLiquidacion } from '@/utils/reservacionPrecio'
import { printTicketElement } from '@/utils/ticketPrinting'
import TicketLogo from '@/components/shared/TicketLogo.vue'

const props = defineProps<TicketPagoEventoProps>()
defineEmits<{ close: [] }>()

const fmt = (n: number) => `$${n.toLocaleString('es-MX', { minimumFractionDigits: 2 })}`

const liquidado = () => props.saldoPendiente <= 0

/** Folio corto y legible para dictar por teléfono; el UUID completo no sirve para eso. */
const folioCorto = () => props.folio.slice(0, 8).toUpperCase()

function fechaEmision(): string {
  const now = new Date()
  return (
    now.toLocaleDateString('es-MX', { year: 'numeric', month: 'short', day: 'numeric' }) +
    ' | ' +
    now.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit' })
  )
}

const $q = useQuasar()
const ticketRef = ref<HTMLElement | null>(null)
const imprimiendo = ref(false)

async function imprimir() {
  if (imprimiendo.value) return
  imprimiendo.value = true
  try {
    // El título es el nombre que sugiere el navegador al guardar como PDF.
    await printTicketElement(ticketRef.value, null, `Pago_${folioCorto()}`)
  } catch (error) {
    $q.notify({ type: 'negative', message: (error as Error).message })
  } finally {
    imprimiendo.value = false
  }
}
</script>

<template>
  <div class="tpe-wrapper">
    <div ref="ticketRef" class="tpe-ticket" data-print-compact>
      <!-- Encabezado -->
      <div class="text-center q-mb-md">
        <TicketLogo :ancho-mm="58" />
        <div class="text-caption text-grey-7">{{ sucursal }}</div>
        <div class="ticket-tipo q-mt-xs">Comprobante de pago</div>
      </div>

      <q-separator class="q-mb-sm" />

      <div class="row justify-between q-mb-md">
        <div>
          <div class="ticket-label">Folio</div>
          <div class="ticket-folio">{{ folioCorto() }}</div>
        </div>
        <div class="text-right">
          <div class="ticket-label">Emitido</div>
          <div class="ticket-value">{{ fechaEmision() }}</div>
        </div>
      </div>

      <q-separator class="q-mb-sm" />

      <!-- Evento -->
      <div class="ticket-section-title q-mb-xs">Datos del evento</div>
      <div class="ticket-row">
        <span>Cliente</span><span class="text-weight-medium">{{ clienteNombre }}</span>
      </div>
      <div class="ticket-row">
        <span>Evento</span><span class="text-weight-medium">{{ tipoEvento }}</span>
      </div>
      <div class="ticket-row">
        <span>Fecha</span><span class="text-weight-medium">{{ fechaEvento }}</span>
      </div>

      <q-separator class="q-my-md" />

      <!-- Pago -->
      <div class="ticket-section-title q-mb-xs">Pago recibido</div>
      <div class="ticket-row">
        <span>Monto pagado</span><span class="text-weight-medium">{{ fmt(montoPagado) }}</span>
      </div>
      <div class="ticket-row">
        <span>Método</span><span class="text-weight-medium">{{ metodosPago }}</span>
      </div>
      <div v-if="notas" class="ticket-row">
        <span>Notas</span><span class="text-weight-medium">{{ notas }}</span>
      </div>

      <q-separator class="q-my-md" />

      <!-- Totales -->
      <div class="ticket-row">
        <span>Total del evento</span><span class="text-weight-medium">{{ fmt(totalEvento) }}</span>
      </div>
      <div class="ticket-row">
        <span>Pagado a la fecha</span>
        <span class="text-weight-medium">{{ fmt(totalPagadoAcumulado) }}</span>
      </div>

      <div class="ticket-saldo" :class="{ 'ticket-saldo--liquidado': liquidado() }">
        <span>{{ liquidado() ? 'Sin saldo pendiente' : 'Saldo pendiente' }}</span>
        <span>{{ fmt(saldoPendiente) }}</span>
      </div>

      <div v-if="!liquidado()" class="ticket-nota">
        {{ avisoLiquidacion(props.fechaLimiteLiquidacion) }}
      </div>

      <div class="text-center text-caption text-grey-7 q-mt-md q-mb-md">
        ¡Gracias por celebrar con nosotros!
      </div>

      <div class="row q-gutter-sm tpe-print-hide">
        <q-btn
          unelevated
          no-caps
          color="primary"
          :label="imprimiendo ? 'Imprimiendo…' : 'Imprimir ticket'"
          :loading="imprimiendo"
          icon="print"
          class="col"
          style="border-radius: 8px; font-weight: 600"
          @click="imprimir"
        />
        <q-btn
          outline
          no-caps
          color="grey-8"
          label="Cerrar"
          class="col"
          style="border-radius: 8px; font-weight: 600"
          @click="$emit('close')"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.tpe-wrapper {
  background: rgba(0, 0, 0, 0.05);
  padding: 24px;
  display: flex;
  justify-content: center;
  border-radius: 12px;
}

.tpe-ticket {
  background: var(--bg-card);
  border-radius: 12px;
  padding: 24px;
  max-width: 420px;
  width: 100%;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
}

.ticket-tipo {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--q-primary);
  text-transform: uppercase;
}

.ticket-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  text-transform: uppercase;
}

.ticket-value {
  font-size: 13px;
  color: var(--text-primary);
}

.ticket-folio {
  font-family: 'Courier New', monospace;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--text-primary);
}

.ticket-section-title {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--text-muted);
  text-transform: uppercase;
}

.ticket-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 12px;
  padding: 3px 0;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.ticket-row > span:last-child {
  color: var(--text-primary);
  text-align: right;
}

.ticket-saldo {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  font-weight: 700;
  font-size: 0.9rem;
  background: rgba(2, 95, 224, 0.08);
  color: var(--q-primary);
}

.ticket-saldo--liquidado {
  background: rgba(63, 168, 52, 0.12);
  color: #2e7d32;
}

.ticket-nota {
  margin-top: 6px;
  font-size: 0.7rem;
  color: var(--text-muted);
  text-align: center;
}
</style>
