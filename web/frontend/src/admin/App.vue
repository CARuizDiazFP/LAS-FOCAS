<!--
  Nombre de archivo: App.vue
  Ubicación de archivo: web/frontend/src/admin/App.vue
  Descripción: Raíz del SPA admin — provee RouterView con AdminLayout
-->
<template>
  <AdminLayout>
    <RouterView />
  </AdminLayout>
</template>

<script setup lang="ts">
import AdminLayout from './components/AdminLayout.vue';
</script>
