<!--
  Nombre de archivo: AdminIngesta.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminIngesta.vue
  Descripción: Hub de navegación del módulo de ingesta — redirige a Servicios SLA o Cámaras
-->
<template>
  <section class="admin-ingesta">
    <h1>Ingesta</h1>
    <p class="section-subtitle">Seleccioná el módulo de ingesta.</p>

    <div class="service-grid">
      <RouterLink to="/admin/ingesta/servicios" class="service-card">
        <span class="card-icon">📊</span>
        <span class="card-title">Servicios SLA</span>
        <span class="card-desc">Carga automática del Excel de Servicios SLA.</span>
      </RouterLink>

      <RouterLink to="/admin/ingesta/camaras" class="service-card">
        <span class="card-icon">📷</span>
        <span class="card-title">Cámaras</span>
        <span class="card-desc">Ingesta masiva de cámaras críticas con baneo administrativo.</span>
      </RouterLink>
    </div>
  </section>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router';
</script>

<style scoped>
.admin-ingesta {
  display: grid;
  gap: var(--space-3);
}
</style>
