<!--
  Nombre de archivo: PanelView.vue
  Ubicación de archivo: web/frontend/src/views/PanelView.vue
  Descripción: Vista principal del panel con tabs Chat, Repetitividad, VLAN, FO, Ciena, Infra
-->
<template>
  <div class="panel-root">
    <nav class="panel-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="['chip', { active: activeTab === tab.id }]"
        @click="activeTab = tab.id"
      >{{ tab.label }}</button>
      <RouterLink class="chip" to="/sla">SLA</RouterLink>
    </nav>
    <div class="panel-content">
      <ChatTab v-show="activeTab === 'chat'" />
      <RepetitividadTab v-show="activeTab === 'rep'" />
      <VlanTab v-show="activeTab === 'vlan'" />
      <FoTab v-show="activeTab === 'fo'" />
      <CienaTab v-show="activeTab === 'ciena'" />
      <InfraTab v-show="activeTab === 'infra'" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import ChatTab from './tabs/ChatTab.vue';
import RepetitividadTab from './tabs/RepetitividadTab.vue';
import VlanTab from './tabs/VlanTab.vue';
import FoTab from './tabs/FoTab.vue';
import CienaTab from './tabs/CienaTab.vue';
import InfraTab from './tabs/InfraTab.vue';

const tabs = [
  { id: 'chat', label: 'Chat' },
  { id: 'rep', label: 'Repetitividad' },
  { id: 'vlan', label: 'VLAN' },
  { id: 'fo', label: 'FO' },
  { id: 'ciena', label: 'Ciena' },
  { id: 'infra', label: 'Infraestructura' },
];

const route = useRoute();
const router = useRouter();
const validTabs = new Set(tabs.map((tab) => tab.id));

function normalizeTab(tab: unknown): string {
  const candidate = typeof tab === 'string' ? tab.toLowerCase() : '';
  return validTabs.has(candidate) ? candidate : 'chat';
}

const activeTab = ref(normalizeTab(route.query.tab));

watch(
  () => route.query.tab,
  (tab) => {
    const normalized = normalizeTab(tab);
    if (normalized !== activeTab.value) {
      activeTab.value = normalized;
    }
  },
);

watch(activeTab, async (tab) => {
  const nextQuery = { ...route.query };
  if (tab === 'chat') {
    delete nextQuery.tab;
  } else {
    nextQuery.tab = tab;
  }
  if (String(route.query.tab ?? '') === String(nextQuery.tab ?? '')) {
    return;
  }
  await router.replace({ query: nextQuery });
});
</script>

<style scoped>
.panel-root { display: flex; flex-direction: column; height: 100%; }
.panel-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 12px 16px;
  background: var(--surface, #111);
  border-bottom: 1px solid var(--border, #2a2a2a);
}
.chip {
  padding: 6px 14px;
  border-radius: 20px;
  font-size: .82rem;
  border: 1px solid var(--border, #2a2a2a);
  background: none;
  cursor: pointer;
  color: var(--text, #e2e8f0);
  text-decoration: none;
  transition: background .15s, border-color .15s;
}
.chip:hover { background: rgba(255,255,255,.06); }
.chip.active { background: var(--primary, #3b82f6); border-color: transparent; color: #fff; }
.panel-content { flex: 1; overflow-y: auto; padding: 16px; }
</style>
