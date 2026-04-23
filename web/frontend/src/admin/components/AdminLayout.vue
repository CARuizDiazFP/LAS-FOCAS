<!--
  Nombre de archivo: AdminLayout.vue
  Ubicación de archivo: web/frontend/src/admin/components/AdminLayout.vue
  Descripción: Layout compartido del panel admin — topbar con navegación y datos de sesión
-->
<template>
  <header class="topbar">
    <div class="brand">LAS-FOCAS</div>
    <nav class="actions">
      <RouterLink class="btn" to="/admin">Inicio</RouterLink>
      <RouterLink class="btn" to="/admin/usuarios">Usuarios</RouterLink>
      <RouterLink class="btn" to="/admin/servicios">Servicios</RouterLink>
      <a class="btn" href="/">Panel</a>
      <a class="btn" href="/logout">Salir</a>
      <span class="user-info">{{ adminUser }}</span>
    </nav>
  </header>
  <main class="container">
    <slot />
  </main>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { getAdminMe } from '../api/admin';

const adminUser = ref('');

onMounted(async () => {
  try {
    const me = await getAdminMe();
    adminUser.value = `${me.username} (${me.role})`;
  } catch {
    // El guard del router ya gestiona redirección si falla
  }
});
</script>
