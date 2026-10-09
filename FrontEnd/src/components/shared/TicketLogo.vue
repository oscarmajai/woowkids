<script setup lang="ts">
import { computed, ref } from 'vue'

/**
 * Logo de Woow Kids para el encabezado de todos los tickets.
 *
 * Usa una versión en blanco y negro (1 bit) a la resolución real de una
 * impresora térmica de 203 dpi: el logo a color sale como una mancha oscura y
 * se pierde el texto. Cada tamaño se dibuja a su ancho exacto en milímetros
 * para que el navegador no tenga que reescalarlo (y volverlo gris).
 */
const props = withDefaults(defineProps<{ anchoMm?: 58 | 80 | 210 }>(), { anchoMm: 80 })

// 46 mm en rollo de 80 (y A4), 34 mm en rollo de 58 / 2".
const chico = computed(() => props.anchoMm === 58)
const src = computed(() => (chico.value ? '/ticket-logo-58.png' : '/ticket-logo-80.png'))
const anchoLogo = computed(() => (chico.value ? '34mm' : '46mm'))

// Si el archivo no carga se oculta: una imagen rota detendría la impresión de
// todo el ticket y es preferible imprimirlo sin logo.
const fallo = ref(false)
</script>

<template>
  <div v-if="!fallo" class="ticket-logo">
    <img :src="src" alt="Woow Kids" :style="{ width: anchoLogo }" @error="fallo = true" />
  </div>
</template>

<style scoped>
.ticket-logo {
  display: flex;
  justify-content: center;
  margin: 0 0 4px;
}
.ticket-logo img {
  display: block;
  height: auto;
  max-width: 100%;
  image-rendering: pixelated;
}
</style>
