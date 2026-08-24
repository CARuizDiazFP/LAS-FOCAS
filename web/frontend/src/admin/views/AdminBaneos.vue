<!--
  Nombre de archivo: AdminBaneos.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminBaneos.vue
  Descripción: Vista /admin/Servicios/Baneos — contenedor de 3 tabs: Baneos Activos (listado agrupado + liberación masiva), Configuración (worker de notificaciones Slack) y Revisión (Cámaras pendientes / Ingresos sin match)
-->
<template>
  <AdminPageHeader
    kicker="Servicios · Automatización"
    title="Baneos"
    subtitle="Grupos baneados, configuración del worker de notificaciones Slack y triage de casos pendientes."
  />

  <div class="tabs" role="tablist">
    <button
      role="tab"
      :aria-selected="tab === 'activos'"
      :class="['tab', { active: tab === 'activos' }]"
      @click="tab = 'activos'"
    >
      Baneos Activos
    </button>
    <button
      role="tab"
      :aria-selected="tab === 'config'"
      :class="['tab', { active: tab === 'config' }]"
      @click="tab = 'config'"
    >
      Configuración
    </button>
    <button
      role="tab"
      :aria-selected="tab === 'revision'"
      :class="['tab', { active: tab === 'revision' }]"
      @click="tab = 'revision'"
    >
      Revisión
    </button>
  </div>

  <BaneosActivosPanel v-if="tab === 'activos'" />
  <BaneosConfigPanel v-if="tab === 'config'" />
  <BaneosRevisionPanel v-if="tab === 'revision'" />
</template>

<script setup lang="ts">
import { ref } from 'vue';

import AdminPageHeader from '../components/AdminPageHeader.vue';
import BaneosActivosPanel from '../components/BaneosActivosPanel.vue';
import BaneosConfigPanel from '../components/BaneosConfigPanel.vue';
import BaneosRevisionPanel from '../components/BaneosRevisionPanel.vue';

const tab = ref<'activos' | 'config' | 'revision'>('activos');
</script>

<style scoped>
.tabs {
  display: flex;
  gap: 6px;
  margin: 16px 0;
  border-bottom: 1px solid var(--color-divider);
}

.tab {
  padding: 8px 16px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 0.9rem;
}

.tab.active {
  color: var(--text);
  border-bottom-color: var(--color-accent);
  font-weight: 600;
}
</style>
