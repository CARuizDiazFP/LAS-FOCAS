<!--
  Nombre de archivo: AdminPageHeader.vue
  Ubicación de archivo: web/frontend/src/admin/components/AdminPageHeader.vue
  Descripción: Cabecera estándar de vista admin (kicker + título + subtítulo), calcada del patrón de ServiciosView.vue
-->
<template>
  <header class="admin-page-header">
    <span class="admin-page-header__kicker">{{ kicker }}</span>
    <div class="admin-page-header__row">
      <h1>{{ title }}</h1>
      <p v-if="subtitle" class="admin-page-header__subtitle">{{ subtitle }}</p>
    </div>
  </header>
</template>

<script setup lang="ts">
defineProps<{
  kicker: string;
  title: string;
  subtitle?: string;
}>();
</script>

<style scoped>
.admin-page-header {
  padding: 0 0 4px;
}

.admin-page-header__kicker {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.admin-page-header__row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
}

.admin-page-header__row h1 {
  font-size: 27px;
  margin: 3px 0 0;
}

.admin-page-header__subtitle {
  margin: 0 0 4px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 52%, transparent);
}
</style>
