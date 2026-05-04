<!--
  Nombre de archivo: PanelLayout.vue
  Ubicación de archivo: web/frontend/src/components/PanelLayout.vue
  Descripción: Layout principal del panel — topbar con datos de sesión y RouterView para contenido
-->
<template>
  <div class="panel-layout">
    <header class="topbar">
      <div class="brand">LAS-FOCAS</div>
      <nav class="actions">
        <RouterLink class="btn subtle" to="/">Panel</RouterLink>
        <RouterLink class="btn subtle" to="/reports-history">Reportes</RouterLink>
        <RouterLink v-if="isAdmin" class="btn subtle" to="/admin">Admin</RouterLink>
        <button class="btn subtle" @click="doLogout">Salir</button>
        <span class="user-info" v-if="username">{{ username }}</span>
      </nav>
    </header>
    <main class="panel-main">
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { useSession } from '../composables/useSession';
import { logout } from '../api/auth';

const { state, clearSession } = useSession();
const router = useRouter();

const username = computed(() => state.value.username);
const isAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');

async function doLogout() {
  try { await logout(); } catch { /* ignorar */ }
  clearSession();
  router.push('/login');
}
</script>

<style scoped>
.panel-layout { display: flex; flex-direction: column; min-height: 100vh; }
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  height: 48px;
  background: var(--surface, #0f0f0f);
  border-bottom: 1px solid var(--border, #2a2a2a);
  position: sticky;
  top: 0;
  z-index: 100;
}
.brand { font-weight: 700; font-size: 1rem; color: var(--text, #e2e8f0); letter-spacing: .05em; }
.actions { display: flex; align-items: center; gap: 8px; }
.user-info { font-size: .82rem; color: var(--muted, #94a3b8); margin-left: 8px; }
.panel-main { flex: 1; }
</style>
