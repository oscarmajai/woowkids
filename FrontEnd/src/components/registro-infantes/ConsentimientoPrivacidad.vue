<script setup lang="ts">
import { ref } from 'vue'
import { useRegistrationStore } from '@/stores/registration'
import BaseDialog from '@/components/ui/BaseDialog.vue'
import AvisoPrivacidadTexto from '@/components/privacidad/AvisoPrivacidadTexto.vue'
import { RUTA_AVISO_PRIVACIDAD } from '@/utils/avisoPrivacidad'

/**
 * Consentimiento del tutor (LFPDPPP): al final del registro, antes de cobrar,
 * se le muestra el aviso simplificado (con enlace al integral) y se deja
 * constancia de que lo aceptó. También puede negarse a las finalidades voluntarias.
 */
const store = useRegistrationStore()
const verAviso = ref(false)

function aceptarDesdeDialogo(): void {
  store.aceptaAvisoPrivacidad = true
  verAviso.value = false
}
</script>

<template>
  <q-card flat bordered class="consent q-mb-md">
    <q-card-section>
      <div class="row items-center q-mb-sm">
        <q-icon name="privacy_tip" size="22px" color="primary" class="q-mr-sm" />
        <span class="text-subtitle1 text-weight-bold">Aviso de privacidad</span>
        <q-space />
        <q-chip v-if="store.avisoAceptado" dense color="positive" text-color="white" icon="check">
          Aceptado
        </q-chip>
      </div>

      <div v-if="store.cargandoAviso" class="consent__note" role="status">
        <q-spinner color="primary" size="18px" />Cargando el aviso de privacidad…
      </div>
      <div v-else-if="store.errorAviso" class="consent__note consent__note--warn" role="alert">
        <q-icon name="error_outline" size="19px" />
        <span class="consent__note-text">{{ store.errorAviso }}</span>
        <q-btn flat dense no-caps label="Reintentar" @click="store.cargarAvisoPrivacidad()" />
      </div>

      <template v-else-if="store.avisoPrivacidad">
        <p class="consent__intro">
          Antes de continuar, muestra al tutor el aviso de privacidad (versión
          {{ store.avisoPrivacidad.version }}) sobre el uso de sus datos y los de los niños.
          <q-btn
            flat
            dense
            no-caps
            color="primary"
            icon="visibility"
            label="Ver aviso"
            class="consent__ver"
            @click="verAviso = true"
          />
        </p>

        <q-checkbox
          v-model="store.aceptaAvisoPrivacidad"
          class="consent__check"
          label="El tutor leyó y acepta el aviso de privacidad"
        />
        <q-checkbox
          v-model="store.rechazaFinalidadesSecundarias"
          class="consent__check"
          :disable="store.step !== 'form'"
          label="El tutor NO desea que sus datos se usen para el programa de lealtad ni para promociones"
        />
        <p v-if="store.rechazaFinalidadesSecundarias" class="consent__hint">
          Este registro no acumulará ni canjeará puntos de lealtad.
        </p>
      </template>
    </q-card-section>

    <BaseDialog
      v-if="store.avisoPrivacidad"
      v-model="verAviso"
      title="Aviso de privacidad"
      :subtitle="`Versión ${store.avisoPrivacidad.version}`"
      icon="privacy_tip"
      :width="640"
      secondary-label="Cerrar"
      primary-label="El tutor acepta"
      @confirm="aceptarDesdeDialogo"
    >
      <AvisoPrivacidadTexto :texto="store.avisoPrivacidad.textoSimplificado" />
      <a :href="RUTA_AVISO_PRIVACIDAD" target="_blank" rel="noopener" class="consent__integral">
        <q-icon name="open_in_new" size="16px" />Leer el aviso de privacidad integral
      </a>
    </BaseDialog>
  </q-card>
</template>

<style scoped lang="scss">
.consent {
  border-radius: 12px;

  &__intro {
    margin: 0 0 6px;
    font-size: 13.5px;
    color: var(--text-body);
  }

  &__ver {
    margin-left: 4px;
  }

  &__check {
    display: flex;
    font-size: 14px;
  }

  &__hint {
    margin: 4px 0 0 40px;
    font-size: 12.5px;
    color: var(--text-secondary);
  }

  &__note {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-radius: 10px;
    background: var(--tone-info-bg);
    color: var(--tone-info-fg);
    font-size: 13.5px;
    font-weight: 600;

    &--warn {
      background: var(--tone-warn-bg);
      color: var(--tone-warn-fg);
    }
  }

  &__note-text {
    flex: 1;
  }

  &__integral {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 8px;
    font-size: 13.5px;
    font-weight: 700;
    color: var(--q-primary);
  }
}
</style>
