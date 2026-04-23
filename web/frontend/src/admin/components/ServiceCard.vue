<!--
  Nombre de archivo: ServiceCard.vue
  Ubicación de archivo: web/frontend/src/admin/components/ServiceCard.vue
  Descripción: Tarjeta reutilizable para el grid de servicios admin
-->
<template>
  <RouterLink :to="to" class="service-card">
    <div class="card-icon">
      <slot name="icon">{{ icon }}</slot>
    </div>
    <div class="card-title">{{ title }}</div>
    <div class="card-desc">{{ description }}</div>
  </RouterLink>
</template>

<script setup lang="ts">
defineProps<{
  to: string;
  title: string;
  description: string;
  icon?: string;
}>();
</script>
