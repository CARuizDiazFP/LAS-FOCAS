<!--
  Nombre de archivo: AdminServicios.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminServicios.vue
  Descripción: Vista /admin/servicios — grid de tarjetas de servicios configurables
-->
<template>
  <h1>Servicios</h1>
  <p class="section-subtitle">Configuración y estado de los servicios del sistema.</p>

  <div class="service-grid">
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
import ServiceCard from '../components/ServiceCard.vue';
</script>
