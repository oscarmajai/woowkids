<script setup lang="ts">
import { onMounted } from 'vue'
import { useAvisoPrivacidadStore } from '@/stores/avisoPrivacidad'
import AvisoPrivacidadTexto from '@/components/privacidad/AvisoPrivacidadTexto.vue'
import { RUTA_AVISO_PRIVACIDAD } from '@/utils/avisoPrivacidad'

/**
 * Aviso de privacidad (versión simplificada) dentro del portal de padres.
 *
 * El portal muestra el nombre y el tiempo de estancia de los menores, así que
 * el aviso va a la vista de quien lo consulta y no solo como un enlace. El
 * aviso integral se abre en otra pestaña para no sacar al tutor de su sesión.
 * Es público: no necesita el token del portal.
 */
const props = withDefaults(defineProps<{ abierto?: boolean }>(), { abierto: false })

const store = useAvisoPrivacidadStore()

onMounted(() => {
  if (!store.vigente) void store.cargarVigente()
})
</script>

<template>
  <section class="aviso-padres" aria-label="Aviso de privacidad">
    <q-expansion-item
      :default-opened="props.abierto"
      icon="privacy_tip"
      label="Aviso de privacidad"
      :caption="
        store.vigente ? `Versión ${store.vigente.version} · cómo usamos tus datos` : undefined
      "
      header-class="aviso-padres__header"
      expand-icon-class="aviso-padres__chevron"
    >
      <div class="aviso-padres__body">
        <div v-if="store.cargandoVigente" class="aviso-padres__estado" role="status">
          <q-spinner color="primary" size="18px" />Cargando el aviso…
        </div>
        <div v-else-if="store.errorVigente" class="aviso-padres__estado" role="alert">
          <span>{{ store.errorVigente }}</span>
          <q-btn
            flat
            dense
            no-caps
            color="primary"
            label="Reintentar"
            @click="store.cargarVigente()"
          />
        </div>
        <AvisoPrivacidadTexto
          v-else-if="store.vigente?.textoSimplificado"
          :texto="store.vigente.textoSimplificado"
        />

        <a
          :href="RUTA_AVISO_PRIVACIDAD"
          target="_blank"
          rel="noopener"
          class="aviso-padres__integral"
        >
          Ver el aviso de privacidad integral
        </a>
      </div>
    </q-expansion-item>
  </section>
</template>

<style scoped lang="scss">
.aviso-padres {
  width: 100%;
  max-width: 480px;
  margin: 0 auto;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--bg-card);
  overflow: hidden;

  &__body {
    padding: 4px 16px 16px;
  }

  &__estado {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13.5px;
    color: var(--text-secondary);
  }

  &__integral {
    display: inline-block;
    margin-top: 12px;
    font-size: 13px;
    font-weight: 700;
    color: var(--q-primary);
  }
}
</style>
