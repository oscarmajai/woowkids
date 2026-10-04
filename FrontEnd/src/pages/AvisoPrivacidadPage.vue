<script setup lang="ts">
import { onMounted } from 'vue'
import { useAvisoPrivacidadStore } from '@/stores/avisoPrivacidad'
import AvisoPrivacidadTexto from '@/components/privacidad/AvisoPrivacidadTexto.vue'
import StateBlock from '@/components/ui/StateBlock.vue'

/** Aviso de privacidad integral vigente. Público (sin sesión) e imprimible. */
const store = useAvisoPrivacidadStore()

onMounted(() => {
  void store.cargarVigente()
})

function imprimir(): void {
  window.print()
}
</script>

<template>
  <q-page class="aviso-page">
    <div class="aviso-page__sheet">
      <header class="aviso-page__head">
        <div class="aviso-page__brand">
          <img src="/woow-kids-mascot.png" alt="" class="aviso-page__mascot" />
          <span class="aviso-page__name">{{ store.vigente?.nombreComercial || 'Woow Kids' }}</span>
        </div>
        <q-btn
          v-if="store.vigente"
          flat
          no-caps
          color="primary"
          icon="print"
          label="Imprimir"
          class="aviso-page__print"
          @click="imprimir"
        />
      </header>

      <div v-if="store.cargandoVigente" class="aviso-page__state" role="status">
        <q-spinner color="primary" size="28px" />Cargando el aviso de privacidad…
      </div>
      <StateBlock
        v-else-if="store.errorVigente"
        variant="error"
        title="No se pudo cargar el aviso de privacidad"
        :body="store.errorVigente"
        action-label="Reintentar"
        @action="store.cargarVigente()"
      />
      <article v-else-if="store.vigente" class="aviso-page__body">
        <AvisoPrivacidadTexto :texto="store.vigente.textoIntegral" />
      </article>
    </div>
  </q-page>
</template>

<style scoped lang="scss">
.aviso-page {
  min-height: 100vh;
  background: var(--bg-main);
  padding: 32px 16px 48px;

  &__sheet {
    max-width: 820px;
    margin: 0 auto;
    background: #fff;
    border: 1px solid var(--border-color);
    border-radius: var(--radius-md);
    padding: 28px 36px 36px;

    @media (max-width: 600px) {
      padding: 20px 18px 28px;
    }
  }

  &__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 20px;
  }

  &__brand {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  &__mascot {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    object-fit: cover;
  }

  &__name {
    font-size: 15px;
    font-weight: 800;
    color: var(--text-strong);
  }

  &__state {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 24px 0;
    color: var(--text-secondary);
    font-weight: 600;
  }
}

@media print {
  .aviso-page {
    padding: 0;
    background: #fff;

    &__sheet {
      max-width: none;
      border: 0;
      padding: 0;
    }

    &__print {
      display: none;
    }
  }
}
</style>
