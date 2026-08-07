<!--
  Nombre de archivo: AdminServicios.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminServicios.vue
  Descripción: Vista /admin/servicios — grid de tarjetas de servicios configurables
-->
<template>
  <AdminPageHeader kicker="Panel admin" title="Servicios" subtitle="Configuración y estado de los servicios del sistema." />

  <div class="service-grid">
    <ServiceCard
      to="/admin/ingesta"
      title="Ingesta"
      description="Carga de Excel de Servicios SLA con barra de progreso y resumen de upsert."
      icon="🍽️"
    />
    <ServiceCard
      to="/admin/Servicios/Baneos"
      title="Baneos"
      description="Notificaciones Slack del worker de cámaras baneadas. Configura intervalo, canales y estado."
      icon="🚫"
    />
    <!-- Futuras tarjetas de servicio se agregan aquí -->
  </div>
</template>

<script setup lang="ts">
import AdminPageHeader from '../components/AdminPageHeader.vue';
import ServiceCard from '../components/ServiceCard.vue';
</script>
