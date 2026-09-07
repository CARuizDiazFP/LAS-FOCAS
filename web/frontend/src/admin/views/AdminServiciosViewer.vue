<!--
  Nombre de archivo: AdminServiciosViewer.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminServiciosViewer.vue
  Descripción: Hub de dashboards de datos operativos para mantenimiento — redirige a Cámaras y próximos módulos
-->
<template>
  <section class="admin-servicios-viewer">
    <AdminPageHeader kicker="Panel admin" title="Viewer" subtitle="Dashboards de datos operativos para mantenimiento." />

    <div class="service-grid">
      <RouterLink to="/admin/servicios/viewer/Camaras" class="service-card">
        <span class="card-icon">📷</span>
        <span class="card-title">Cámaras</span>
        <span class="card-desc">Listado de Cámaras raíz y detección de duplicados por nombre.</span>
      </RouterLink>

      <RouterLink to="/admin/servicios/viewer/Botellas" class="service-card">
        <span class="card-icon">🍾</span>
        <span class="card-title">Botellas</span>
        <span class="card-desc">Listado de Botellas (Cromo + legado) y detección de duplicados dentro de la misma Cámara padre.</span>
      </RouterLink>

      <!-- Futuros dashboards de datos operativos se agregan aquí -->
    </div>
  </section>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router';

import AdminPageHeader from '../components/AdminPageHeader.vue';
</script>

<style scoped>
.admin-servicios-viewer {
  display: grid;
  gap: var(--space-3);
}
</style>
