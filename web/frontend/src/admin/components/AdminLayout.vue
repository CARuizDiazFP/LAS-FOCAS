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
      <button class="btn" @click="doLogout">Salir</button>
      <span class="user-info">{{ adminUser }}</span>
    </nav>
  </header>
  <main class="container">
    <RouterView />
  </main>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { getAdminMe } from '../api/admin';
import { logout } from '../../api/auth';
import { useSession } from '../../composables/useSession';

const { clearSession } = useSession();
const router = useRouter();
const adminUser = ref('');

onMounted(async () => {
  try {
    const me = await getAdminMe();
    adminUser.value = `${me.username} (${me.role})`;
  } catch {
    // El guard del router ya gestiona redirección si falla
  }
});

async function doLogout() {
  try { await logout(); } catch { /* ignorar */ }
  clearSession();
  router.push('/login');
}
</script>
