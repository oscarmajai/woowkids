<template>
  <div class="edit-backdrop" @click.self="$emit('close')">
    <div class="edit-card" role="dialog" aria-modal="true">
      <div v-if="isLoading" class="edit-card__loading">
        <q-spinner size="32px" color="primary" />
        <span>Cargando detalle…</span>
      </div>

      <template v-else-if="orden">
        <header class="edit-card__head">
          <span class="edit-card__icon"><q-icon name="edit" size="22px" /></span>
          <div class="edit-card__titles">
            <span class="edit-card__title">Editar orden #{{ orden.ticket_numero }}</span>
            <span class="edit-card__subtitle">Selecciona los productos a quitar</span>
          </div>
          <q-btn flat round dense icon="close" aria-label="Cerrar" @click="$emit('close')" />
        </header>

        <div class="edit-card__body">
          <div class="edit-list">
            <label class="edit-list__head">
              <q-checkbox
                :model-value="todosSeleccionados"
                dense
                color="negative"
                @update:model-value="toggleTodos"
              />
              <span>Seleccionar todo</span>
              <span class="edit-list__count">{{ idsAEliminar.length }} seleccionados</span>
            </label>
            <div
              v-for="item in itemsVisibles"
              :key="item.key"
              class="edit-list__row"
              :class="{ 'edit-list__row--on': selectedKeys.has(item.key) }"
              @click="toggleItem(item.key)"
            >
              <q-checkbox
                :model-value="selectedKeys.has(item.key)"
                dense
                color="negative"
                @click.stop
                @update:model-value="toggleItem(item.key)"
              />
              <div class="edit-list__info">
                <span class="edit-list__name">{{ item.producto_nombre }}</span>
                <span class="edit-list__meta">
                  {{ item.cantidad }} × ${{ Number(item.precio_unitario).toFixed(2) }}
                  <template v-if="item.notas_especiales"> · {{ item.notas_especiales }}</template>
                  <template v-if="item.tipo === 'combo' && item.hijos">
                    · {{ item.hijos.map((h) => `${h.cantidad}× ${h.producto_nombre}`).join(', ') }}
                  </template>
                </span>
              </div>
              <span class="edit-list__price">${{ item.importe.toFixed(2) }}</span>
            </div>
          </div>

          <dl class="edit-totals">
            <div>
              <dt>Total original</dt>
              <dd>${{ Number(orden.total_final).toFixed(2) }}</dd>
            </div>
            <div>
              <dt>A devolver</dt>
              <dd>−${{ totalSeleccionado.toFixed(2) }}</dd>
            </div>
            <div class="edit-totals__net">
              <dt>Nuevo total</dt>
              <dd>${{ (Number(orden.total_final) - totalSeleccionado).toFixed(2) }}</dd>
            </div>
          </dl>

          <div class="edit-callout">
            <q-icon name="info" size="19px" />
            Se pedirá confirmación. Los insumos de los productos quitados regresan al inventario.
          </div>
        </div>

        <footer class="edit-card__foot">
          <q-btn outline label="Cancelar" @click="$emit('close')" />
          <q-btn
            unelevated
            color="negative"
            :loading="guardando"
            :disable="idsAEliminar.length === 0"
            :label="
              idsAEliminar.length === orden.detalles.length ? 'Cancelar orden' : 'Quitar productos'
            "
            @click="confirmarEliminar"
          />
        </footer>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useQuasar } from 'quasar'
import { obtenerDetalleOrden } from '@/services/historialService'
import { esOrdenModificada, mensajeDeError } from '@/utils/errorHandler'
import { agruparPorRenglon, resumirHijos } from '@/utils/renglonesOrden'
import { useCancelarComanda } from '@/composables/useCancelarComanda'
import { modificarDetallesComanda } from '@/services/comandaService'
import MotivoCancelacionDialog from './MotivoCancelacionDialog.vue'
import type { DetalleOrden, DetalleProducto } from '@/api/historialApi'

interface DisplayItem {
  key: string
  tipo: 'combo' | 'suelto'
  producto_nombre: string
  cantidad: number
  precio_unitario: number
  importe: number
  ids: string[]
  notas_especiales?: string | null
  hijos?: DetalleProducto[]
}

const props = defineProps<{ comandaId: string }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'orden-actualizada'): void
}>()

const $q = useQuasar()
const { cancelarComanda } = useCancelarComanda()
const isLoading = ref(true)
const guardando = ref(false)
const orden = ref<DetalleOrden | null>(null)
const selectedKeys = ref<Set<string>>(new Set())

// Un renglón por producto suelto o por combo, cada combo con sus propios
// productos (por renglón, no por nombre): quitar un combo dividido no arrastra
// los productos del otro.
const itemsVisibles = computed<DisplayItem[]>(() => {
  if (!orden.value) return []
  return agruparPorRenglon(orden.value.detalles).map(({ renglon, hijos }) => ({
    key: `${hijos.length ? 'combo' : 'suelto'}-${renglon.id}`,
    tipo: hijos.length ? 'combo' : 'suelto',
    producto_nombre: renglon.producto_nombre,
    cantidad: renglon.cantidad,
    precio_unitario: renglon.precio_unitario,
    importe: renglon.importe,
    ids: [renglon.id, ...hijos.map((h) => h.id)],
    notas_especiales: renglon.notas_especiales,
    ...(hijos.length ? { hijos: resumirHijos(hijos) } : {}),
  }))
})

const todosSeleccionados = computed(() => {
  if (itemsVisibles.value.length === 0) return false
  return itemsVisibles.value.every((item) => selectedKeys.value.has(item.key))
})

const totalSeleccionado = computed(() => {
  return itemsVisibles.value
    .filter((item) => selectedKeys.value.has(item.key))
    .reduce((sum, item) => sum + item.importe, 0)
})

const idsAEliminar = computed(() => {
  const ids: string[] = []
  for (const item of itemsVisibles.value) {
    if (selectedKeys.value.has(item.key)) ids.push(...item.ids)
  }
  return ids
})

async function cargarOrden() {
  try {
    orden.value = await obtenerDetalleOrden('comanda', props.comandaId)
  } finally {
    isLoading.value = false
  }
}

onMounted(cargarOrden)

function toggleItem(key: string) {
  const next = new Set(selectedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selectedKeys.value = next
}

function toggleTodos() {
  if (todosSeleccionados.value) {
    selectedKeys.value = new Set()
  } else {
    selectedKeys.value = new Set(itemsVisibles.value.map((item) => item.key))
  }
}

async function confirmarEliminar() {
  if (idsAEliminar.value.length === 0 || !orden.value) return

  const esCancelacionTotal = idsAEliminar.value.length === orden.value.detalles.length

  if (esCancelacionTotal) {
    $q.dialog({
      component: MotivoCancelacionDialog,
      componentProps: {
        titulo: 'Cancelar orden completa',
        subtitulo: 'Se eliminarán todos los productos. La orden será cancelada automáticamente.',
        botonLabel: 'Cancelar orden',
      },
    }).onOk((motivo: string) => ejecutarEliminacion(motivo))
  } else {
    const restantes = orden.value.detalles.length - idsAEliminar.value.length
    $q.dialog({
      title: `Eliminar ${idsAEliminar.value.length} producto(s)`,
      message: `Quedará(n) ${restantes} producto(s) con un total recalculado. ¿Continuar?`,
      cancel: { label: 'No', flat: true, color: 'grey-7' },
      ok: { label: 'Eliminar productos', color: 'negative' },
      persistent: true,
    }).onOk(() => ejecutarEliminacion())
  }
}

async function ejecutarEliminacion(motivoCancelacion?: string) {
  if (!orden.value) return
  guardando.value = true

  try {
    const esCancelacionTotal = idsAEliminar.value.length === orden.value.detalles.length

    if (esCancelacionTotal) {
      // Quitar todo es cancelar la orden: va por el mismo flujo que "Cancelar
      // orden" (revierte inventario y, si está pagada, pide el PIN de un
      // administrador y registra la devolución en caja).
      const cancelada = await cancelarComanda(props.comandaId, motivoCancelacion ?? '')
      if (!cancelada) return
    } else {
      // Con la versión que se leyó; si la orden cambió en otra pestaña o
      // dispositivo, el backend responde 409 COMANDA_MODIFICADA sin tocar nada.
      await modificarDetallesComanda(props.comandaId, idsAEliminar.value, undefined, {
        modificadoEsperado: orden.value.modificado ?? undefined,
      })
    }

    $q.notify({
      type: 'positive',
      message: esCancelacionTotal
        ? 'Orden cancelada correctamente.'
        : 'Productos eliminados. Total recalculado.',
      position: 'top',
      timeout: 2500,
      icon: 'check_circle',
    })

    emit('orden-actualizada')
    emit('close')
  } catch (err: unknown) {
    if (esOrdenModificada(err)) {
      // Se recarga la orden y se limpia la selección para que el cajero
      // decida otra vez sobre lo que hay ahora.
      selectedKeys.value = new Set()
      await cargarOrden()
      $q.notify({
        type: 'warning',
        message: mensajeDeError(err, 'La orden cambió mientras la editabas.'),
        caption: 'Se recargó la orden. Revisa los productos y vuelve a intentarlo.',
        position: 'top',
        timeout: 6000,
      })
      return
    }
    const msg = mensajeDeError(err, 'No se pudo modificar la orden.')
    $q.notify({ type: 'negative', message: msg, position: 'top', timeout: 4000 })
  } finally {
    guardando.value = false
  }
}
</script>

<style scoped lang="scss">
.edit-backdrop {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(11, 20, 80, 0.32);
}

.edit-card {
  width: 540px;
  max-width: 100%;
  max-height: 100%;
  background: #fff;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-dialog);
  display: flex;
  flex-direction: column;
  overflow: hidden;

  &__loading {
    min-height: 220px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    color: var(--text-secondary);
  }

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
    background: var(--tone-warn-bg);
    color: var(--tone-warn-fg);
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
    color: var(--text-secondary);
  }

  &__body {
    padding: 20px 24px;
    display: flex;
    flex-direction: column;
    gap: 18px;
    overflow-y: auto;
  }

  &__foot {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
    padding: 16px 24px;
    border-top: 1px solid var(--border-soft);
    background: var(--bg-subtle);

    :deep(.q-btn) {
      min-height: 42px;
    }
  }
}

.edit-list {
  border: 1px solid var(--border-color);
  border-radius: 12px;
  overflow: hidden;

  &__head {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 14px;
    background: var(--bg-subtle);
    border-bottom: 1px solid var(--border-soft);
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--text-secondary);
    cursor: pointer;
  }

  &__count {
    margin-left: auto;
  }

  &__row {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 11px 14px;
    border-bottom: 1px solid #f1f3f7;
    cursor: pointer;

    &:last-child {
      border-bottom: 0;
    }

    &--on {
      background: #fff7f7;
    }
  }

  &__info {
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
    min-width: 0;
  }

  &__name {
    font-size: 13.5px;
    font-weight: 700;
    color: var(--text-primary);
  }

  &__meta {
    font-size: 12px;
    color: var(--text-secondary);
  }

  &__price {
    font-size: 13.5px;
    font-weight: 700;
    color: var(--text-primary);
    font-variant-numeric: tabular-nums;
  }
}

.edit-totals {
  margin: 0;
  padding: 14px 16px;
  border-radius: 12px;
  background: #f6f8fc;
  display: flex;
  flex-direction: column;
  gap: 8px;

  div {
    display: flex;
    justify-content: space-between;
    font-size: 13.5px;
    color: #475569;
  }

  dd {
    margin: 0;
    font-variant-numeric: tabular-nums;
  }

  &__net {
    font-size: 20px !important;
    font-weight: 800;
    color: var(--text-strong) !important;
  }
}

.edit-callout {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--tone-warn-bg);
  color: var(--tone-warn-fg);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
}
</style>
