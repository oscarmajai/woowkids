<template>
  <div class="reg-done">
    <div class="reg-done__main">
      <div class="reg-done__banner">
        <span class="reg-done__check"><q-icon name="check" size="28px" /></span>
        <div>
          <h2 class="reg-done__title">Registro completado</h2>
          <p class="reg-done__text">
            {{ nombres }} {{ store.savedChildren.length > 1 ? 'ya pueden' : 'ya puede' }} entrar al
            área de juegos.
          </p>
        </div>
      </div>

      <div class="reg-done__kids">
        <div v-for="child in store.savedChildren" :key="child.id" class="reg-kid">
          <div class="reg-kid__info">
            <span class="reg-kid__name">{{ child.name }}</span>
            <span class="reg-kid__meta">
              {{ store.isEventoMode ? store.horasEvento : child.estimatedTime }} · salida
              {{ scheduledExit(child) }}
            </span>
            <span v-if="notaVisible(child.notes)" class="reg-kid__notes">
              <q-icon name="medical_information" size="15px" />
              {{ notaVisible(child.notes) }}
            </span>
          </div>
          <span class="reg-kid__band">{{ getBraceletLabel(child.rfidBracelet) }}</span>
        </div>
      </div>

      <div v-if="qrCodeUrl" class="reg-done__note">
        <q-icon name="qr_code_2" size="20px" />
        El tutor puede escanear el QR del comprobante para ver el tiempo restante desde su teléfono.
      </div>

      <div v-if="store.advertenciaEfectivoFromServer" class="reg-done__note reg-done__note--warn">
        <q-icon name="warning" size="20px" />
        {{ store.advertenciaEfectivoFromServer }}
      </div>

      <div class="reg-done__actions">
        <q-btn
          outline
          icon="badge"
          label="Ir a Control de Acceso"
          :to="{ name: 'estancias-control-acceso' }"
        />
        <q-btn
          unelevated
          color="primary"
          icon="person_add"
          label="Nuevo registro"
          @click="$emit('nuevo')"
        />
      </div>
    </div>

    <div class="voucher-wrapper">
      <ComprobanteEstancia ref="voucherRef" :datos="datosComprobante" />
      <q-btn
        outline
        icon="print"
        :label="isPrinting ? 'Imprimiendo…' : 'Imprimir comprobante'"
        class="voucher__print print-hide"
        :loading="isPrinting"
        :disable="!qrCodeUrl"
        @click="printVoucher"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, nextTick } from 'vue'
import { useQuasar } from 'quasar'
import { printTicketElement } from '@/utils/ticketPrinting'
import { useRegistrationStore } from '@/stores/registration'
import type { Child } from '@/stores/registration'
import { useAuthStore } from '@/stores/auth'
import { notaVisible } from '@/utils/notasNino'
import { horaComprobante, qrPortalPadres } from '@/utils/portalPadres'
import type { DatosComprobanteEstancia } from '@/types/comprobanteEstancia'
import ComprobanteEstancia from './ComprobanteEstancia.vue'

defineEmits<{ (e: 'nuevo'): void }>()

const store = useRegistrationStore()
const authStore = useAuthStore()
const qrCodeUrl = ref('')
const voucherRef = ref<InstanceType<typeof ComprobanteEstancia> | null>(null)
const isPrinting = ref(false)
const $q = useQuasar()
const issuedAt = new Date()

const branchName = computed(() => authStore.currentBranchName || 'Sucursal')
const cashierName = computed(() => authStore.currentUser?.name || 'Cajero')

async function generarQR() {
  // El QR lleva el código opaco del portal de padres (A17), nunca el
  // registroId: el UUID del registro ya no da acceso.
  if (store.codigoAccesoPadres) {
    qrCodeUrl.value = await qrPortalPadres(store.codigoAccesoPadres)
  }
}

onMounted(generarQR)

const datosComprobante = computed<DatosComprobanteEstancia>(() => ({
  sucursal: branchName.value,
  cajero: cashierName.value,
  fecha: issuedAt,
  tutor: store.tutor.fullName,
  telefono: store.tutor.phone,
  ninos: store.savedChildren.map((c) => ({ nombre: c.name, edad: c.age, notas: c.notes })),
  salidaEstimada: maxScheduledExit(),
  total: Number(store.totalFromServer ?? store.total),
  qrCodeUrl: qrCodeUrl.value,
}))

function scheduledExitDate(child: Child): Date {
  const time = store.isEventoMode ? store.horasEvento : child.estimatedTime
  const hours = parseInt(time) || 8
  const d = new Date(issuedAt)
  d.setHours(d.getHours() + hours)
  return d
}

function scheduledExit(child: Child) {
  return horaComprobante(scheduledExitDate(child))
}

// Si los niños tienen tiempos distintos, el ticket impreso (uno por
// registro, no por niño) muestra la salida más tardía: el tutor no debe
// llegar antes de que el último niño esté listo.
function maxScheduledExit() {
  const fechas = store.savedChildren.map((c) => scheduledExitDate(c).getTime())
  if (fechas.length === 0) return '—'
  return horaComprobante(new Date(Math.max(...fechas)))
}

const nombres = computed(() => {
  const n = store.savedChildren.map((c) => c.name.split(' ')[0])
  return n.length > 1 ? `${n.slice(0, -1).join(', ')} y ${n.at(-1)}` : (n[0] ?? '')
})

async function printVoucher() {
  if (isPrinting.value) return
  isPrinting.value = true
  try {
    await generarQR()
    await nextTick()
    await printTicketElement(voucherRef.value?.raiz ?? null)
  } catch (error) {
    $q.notify({ type: 'negative', message: (error as Error).message })
  } finally {
    isPrinting.value = false
  }
}

function getBraceletLabel(braceletId: string) {
  return store.etiquetaPulsera(braceletId)
}
</script>

<style scoped lang="scss">
.reg-done {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 24px;
  align-items: start;

  @media (max-width: 1000px) {
    grid-template-columns: minmax(0, 1fr);
  }

  &__main {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  &__banner {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 22px 24px;
    border: 1px solid #b9e2b2;
    border-radius: var(--radius-md);
    background: var(--tone-ok-bg);
  }

  &__check {
    width: 52px;
    height: 52px;
    border-radius: 26px;
    background: var(--tone-ok-dot);
    color: #fff;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  &__title {
    margin: 0;
    font-size: 24px;
    line-height: 1.25;
    font-weight: 800;
    color: var(--tone-ok-fg);
  }

  &__text {
    margin: 2px 0 0;
    font-size: 14.5px;
    color: #33532f;
  }

  &__kids {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 14px;
  }

  &__note {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    border-radius: 12px;
    background: var(--tone-info-bg);
    color: var(--tone-info-fg);
    font-size: 13.5px;
    font-weight: 600;

    &--warn {
      background: var(--tone-warn-bg);
      color: var(--tone-warn-fg);
    }
  }

  &__actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: 8px;

    :deep(.q-btn) {
      min-height: 48px;
    }
  }
}

.reg-kid {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 16px 18px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: #fff;

  &__info {
    display: flex;
    flex-direction: column;
    gap: 4px;
    flex: 1;
    min-width: 0;
  }

  &__name {
    font-size: 15px;
    font-weight: 800;
    color: var(--text-strong);
  }

  &__meta {
    font-size: 12.5px;
    color: var(--text-secondary);
  }

  &__notes {
    display: flex;
    align-items: flex-start;
    gap: 4px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--tone-warn-fg);
  }

  &__band {
    padding: 3px 8px;
    border-radius: 6px;
    background: #f1f4f9;
    font-family: ui-monospace, Menlo, monospace;
    font-size: 12.5px;
    font-weight: 700;
    color: var(--text-body);
  }
}

/* Vista en pantalla del comprobante — el layout de impresión es universal (ver useTicketPrint/printTicketElement) */
.voucher-wrapper {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.voucher__print {
  min-height: 48px;
}
</style>
