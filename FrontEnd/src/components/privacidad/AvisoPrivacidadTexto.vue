<script setup lang="ts">
import { computed } from 'vue'
import { parsearAviso } from '@/utils/avisoPrivacidad'

/** Texto del aviso de privacidad, con títulos, secciones y viñetas. */
const props = defineProps<{ texto: string }>()

const bloques = computed(() => parsearAviso(props.texto))
</script>

<template>
  <div class="aviso-texto">
    <template v-for="(bloque, i) in bloques" :key="i">
      <h1 v-if="bloque.tipo === 'titulo'" class="aviso-texto__titulo">{{ bloque.texto }}</h1>
      <h2 v-else-if="bloque.tipo === 'seccion'" class="aviso-texto__seccion">
        {{ bloque.texto }}
      </h2>
      <ul v-else-if="bloque.tipo === 'lista'" class="aviso-texto__lista">
        <li v-for="(item, j) in bloque.items" :key="j">{{ item }}</li>
      </ul>
      <p v-else class="aviso-texto__parrafo">{{ bloque.texto }}</p>
    </template>
  </div>
</template>

<style scoped lang="scss">
.aviso-texto {
  color: var(--text-body);
  font-size: 14.5px;
  line-height: 1.6;

  &__titulo {
    margin: 0 0 12px;
    font-size: 20px;
    line-height: 1.3;
    font-weight: 800;
    letter-spacing: 0.01em;
    color: var(--text-strong);
  }

  &__seccion {
    margin: 22px 0 8px;
    font-size: 15.5px;
    line-height: 1.35;
    font-weight: 800;
    color: var(--text-strong);
    break-after: avoid;
  }

  &__parrafo {
    margin: 0 0 10px;
  }

  &__lista {
    margin: 0 0 10px;
    padding-left: 22px;

    li + li {
      margin-top: 4px;
    }
  }
}
</style>
