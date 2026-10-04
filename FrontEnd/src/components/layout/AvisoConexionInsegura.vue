<script setup lang="ts">
import { conexionInsegura, urlInstalarCertificado, urlSegura } from '@/utils/conexionSegura'

const visible = conexionInsegura()
</script>

<template>
  <div v-if="visible" class="aviso-inseguro" role="alert">
    <q-icon name="gpp_maybe" size="20px" />
    <span class="aviso-inseguro__texto">
      Conexión no segura: la caja, el punto de venta y la cámara no funcionan así.
    </span>
    <a class="aviso-inseguro__link" :href="urlSegura()">Abrir con HTTPS</a>
    <a class="aviso-inseguro__link" :href="urlInstalarCertificado()">Instalar certificado</a>
  </div>
</template>

<style scoped lang="scss">
.aviso-inseguro {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 9000;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  padding: 10px 16px;
  background: #b42318;
  color: #fff;
  font-size: 13.5px;
  font-weight: 600;

  &__texto {
    flex: 1 1 260px;
  }

  &__link {
    color: #fff;
    text-decoration: underline;
    white-space: nowrap;
  }
}
</style>
