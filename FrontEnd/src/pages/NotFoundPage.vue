<script setup lang="ts">
import { useRouter } from 'vue-router'
import StateBlock from '@/components/ui/StateBlock.vue'

/**
 * B12: ruta inexistente con sesión activa. Antes el comodín redirigía a
 * /login y mostraba el formulario aunque la sesión era válida.
 */
const router = useRouter()

function irAInicio(): void {
  void router.push({ name: 'home' })
}
</script>

<template>
  <q-page class="page-content">
    <div class="state-card">
      <StateBlock
        variant="no-results"
        title="Página no encontrada"
        body="La dirección no existe o cambió. Revisa el enlace o vuelve al inicio."
        action-label="Ir al inicio"
        action-icon="home"
        @action="irAInicio"
      />
    </div>
  </q-page>
</template>

<style scoped lang="scss">
.state-card {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
}
</style>
