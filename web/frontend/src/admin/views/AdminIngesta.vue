<!--
  Nombre de archivo: AdminIngesta.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminIngesta.vue
  Descripción: Hub de navegación del módulo de ingesta — redirige a Servicios SLA, Cámaras o Cromo
-->
<template>
  <section class="admin-ingesta">
    <AdminPageHeader kicker="Panel admin" title="Ingesta" subtitle="Seleccioná el módulo de ingesta." />

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

      <RouterLink to="/admin/ingesta/cromo" class="service-card">
        <span class="card-icon">🧵</span>
        <span class="card-title">Cromo</span>
        <span class="card-desc">Inventario de fibra óptica desde Cromo Red, con progreso en vivo.</span>
      </RouterLink>
    </div>
  </section>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router';

import AdminPageHeader from '../components/AdminPageHeader.vue';
</script>

<style scoped>
.admin-ingesta {
  display: grid;
  gap: var(--space-3);
}
</style>
