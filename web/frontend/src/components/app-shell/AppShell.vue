<!--
  Nombre de archivo: AppShell.vue
  Ubicación de archivo: web/frontend/src/components/app-shell/AppShell.vue
  Descripción: Shell del SPA sobre el sistema Nocturne — sidebar compacto de 224px con iconos Phosphor, perfil al pie
-->
<template>
  <div class="app-shell">
    <div class="app-shell__body">
      <aside class="app-shell__sidebar" aria-label="Navegación principal">
        <header class="app-shell__sidebar-header">
          <div class="app-shell__brand">
            <span class="app-shell__brand-mark" aria-hidden="true"><i class="ph ph-broadcast"></i></span>
            <span class="app-shell__brand-text">LAS-FOCAS</span>
          </div>
          <RouterLink
            v-if="isAdmin"
            class="app-shell__gear"
            to="/admin"
            title="Configuración"
            aria-label="Configuración"
          >
            <i class="ph ph-gear" aria-hidden="true"></i>
          </RouterLink>
          <button
            v-else
            class="app-shell__gear is-disabled"
            type="button"
            title="Configuración no disponible"
            aria-label="Configuración no disponible"
            aria-disabled="true"
            disabled
          >
            <i class="ph ph-gear" aria-hidden="true"></i>
          </button>
        </header>

        <nav class="app-shell__sidebar-nav">
          <RouterLink
            v-for="item in primaryLinks"
            :key="item.id"
            :to="item.to"
            :class="['app-shell__link', { 'is-active': isSidebarLinkActive(item.id) }]"
          >
            <span v-if="isSidebarLinkActive(item.id)" class="app-shell__link-accent" aria-hidden="true"></span>
            <i :class="['ph', item.icon]" aria-hidden="true"></i>
            <span class="app-shell__link-label">{{ item.label }}</span>
            <small v-if="item.count !== undefined" class="app-shell__link-count">{{ item.count }}</small>
          </RouterLink>

          <div class="app-shell__divider" role="separator"></div>

          <section v-for="module in sidebarModules" :key="module.id" class="app-shell__module">
            <button
              type="button"
              :class="['app-shell__link', 'app-shell__module-trigger', { 'is-active': isModuleActive(module.id) }]"
              :aria-controls="`submenu-${module.id}`"
              :aria-expanded="isModuleExpanded(module.id)"
              @click="toggleModule(module.id)"
            >
              <span v-if="isModuleActive(module.id)" class="app-shell__link-accent" aria-hidden="true"></span>
              <i :class="['ph', module.icon]" aria-hidden="true"></i>
              <span class="app-shell__link-label">{{ module.label }}</span>
              <i
                :class="['ph', isModuleExpanded(module.id) ? 'ph-caret-down' : 'ph-caret-right', 'app-shell__module-chevron']"
                aria-hidden="true"
              ></i>
            </button>

            <Transition name="app-shell-submenu">
              <div
                v-show="isModuleExpanded(module.id)"
                :id="`submenu-${module.id}`"
                class="app-shell__submenu"
              >
                <RouterLink
                  v-for="item in module.items"
                  :key="item.id"
                  :to="item.to"
                  :class="['app-shell__sublink', { 'is-active': isSidebarLinkActive(item.id) }]"
                >
                  {{ item.label }}
                </RouterLink>
              </div>
            </Transition>
          </section>
        </nav>

        <footer class="app-shell__sidebar-footer">
          <button class="app-shell__profile" type="button" :title="profileTooltip" aria-label="Perfil">
            <i class="ph-fill ph-user-circle app-shell__profile-icon" aria-hidden="true"></i>
            <span class="app-shell__profile-text">
              <strong>{{ profileName }}</strong>
              <small v-if="roleLabel">{{ roleLabel }}</small>
            </span>
            <i class="ph ph-caret-up-down app-shell__profile-caret" aria-hidden="true"></i>
          </button>
        </footer>
      </aside>

      <main class="app-shell__main">
        <div id="dynamic-module-actions" class="app-shell__module-actions">
          <slot name="module-actions"></slot>
        </div>
        <RouterView />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, type RouteLocationNormalizedLoaded, type RouteLocationRaw } from 'vue-router';
import { useSession } from '../../composables/useSession';

type SidebarViewId =
  | 'home'
  | 'infraFo'
  | 'servicios'
  | 'repetitividad'
  | 'sla'
  | 'historial'
  | 'alarmasCiena'
  | 'comparadorVlans'
  | 'comparadorFo'
  | 'verificadorCromo'
  | 'none';

type ExpandableModuleId = 'reportes' | 'dwdmCiena' | 'toolKit';

interface SidebarItem {
  id: Exclude<SidebarViewId, 'none'>;
  label: string;
  icon: string;
  count?: number;
  to: RouteLocationRaw;
}

interface SidebarModule {
  id: ExpandableModuleId;
  label: string;
  icon: string;
  items: Omit<SidebarItem, 'icon' | 'count'>[];
}

const route = useRoute();
const { state } = useSession();

const username = computed(() => state.value.username ?? '');
const roleLabel = computed(() => state.value.role ?? '');
const isAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');
const expandedModule = ref<ExpandableModuleId | null>(null);
const currentView = ref<SidebarViewId>('none');
const profileName = computed(() => username.value || 'Perfil');
const profileTooltip = computed(() => {
  const parts = [username.value, roleLabel.value].filter(Boolean);
  return parts.length > 0 ? `Perfil: ${parts.join(' · ')}` : 'Perfil';
});

const primaryLinks: SidebarItem[] = [
  {
    id: 'home',
    label: 'Home',
    icon: 'ph-chat-circle-dots',
    to: { path: '/' },
  },
  {
    id: 'infraFo',
    label: 'Infraestructura FO',
    icon: 'ph-tree-structure',
    to: { path: '/infra' },
  },
  {
    id: 'servicios',
    label: 'Servicios',
    icon: 'ph-globe-hemisphere-west',
    to: { path: '/servicios' },
  },
];

const sidebarModules: SidebarModule[] = [
  {
    id: 'reportes',
    label: 'Reportes',
    icon: 'ph-chart-line-up',
    items: [
      { id: 'repetitividad', label: 'Repetitividad', to: { path: '/repetitividad' } },
      { id: 'sla', label: 'SLA', to: { path: '/sla' } },
      { id: 'historial', label: 'Historial', to: { path: '/reports-history' } },
    ],
  },
  {
    id: 'dwdmCiena',
    label: 'DWDM Ciena',
    icon: 'ph-waveform',
    items: [
      { id: 'alarmasCiena', label: 'Alarmas Ciena', to: { path: '/dwdm/ciena' } },
    ],
  },
  {
    id: 'toolKit',
    label: 'Tool Kit',
    icon: 'ph-toolbox',
    items: [
      { id: 'comparadorVlans', label: 'Comparador de VLANs', to: { path: '/toolkit/vlan' } },
      { id: 'comparadorFo', label: 'Comparador FO', to: { path: '/fo' } },
      { id: 'verificadorCromo', label: 'Verificador Cromo', to: { path: '/infra/cromo/verificador' } },
    ],
  },
];

const moduleByView: Partial<Record<SidebarViewId, ExpandableModuleId>> = {
  repetitividad: 'reportes',
  sla: 'reportes',
  historial: 'reportes',
  alarmasCiena: 'dwdmCiena',
  comparadorVlans: 'toolKit',
  comparadorFo: 'toolKit',
  verificadorCromo: 'toolKit',
};

function resolveCurrentView(currentRoute: RouteLocationNormalizedLoaded): SidebarViewId {
  if (currentRoute.path === '/') {
    return 'home';
  }

  if (currentRoute.path === '/infra') {
    return 'infraFo';
  }
  if (currentRoute.path === '/servicios') {
    return 'servicios';
  }
  if (currentRoute.path.startsWith('/servicios/ID/')) {
    return 'servicios';
  }
  if (currentRoute.path === '/repetitividad') {
    return 'repetitividad';
  }
  if (currentRoute.path === '/dwdm/ciena') {
    return 'alarmasCiena';
  }
  if (currentRoute.path === '/toolkit/vlan') {
    return 'comparadorVlans';
  }
  if (currentRoute.path === '/fo') {
    return 'comparadorFo';
  }
  if (currentRoute.path === '/sla') {
    return 'sla';
  }
  if (currentRoute.path === '/reports-history') {
    return 'historial';
  }
  if (currentRoute.path.startsWith('/infra/Camaras/')) {
    return 'infraFo';
  }
  if (currentRoute.path === '/infra/cromo/verificador') {
    return 'verificadorCromo';
  }

  return 'none';
}

function isSidebarLinkActive(viewId: SidebarItem['id']): boolean {
  return currentView.value === viewId;
}

function isModuleExpanded(moduleId: ExpandableModuleId): boolean {
  return expandedModule.value === moduleId;
}

function isModuleActive(moduleId: ExpandableModuleId): boolean {
  if (currentView.value === 'none') {
    return false;
  }
  return moduleByView[currentView.value] === moduleId;
}

function toggleModule(moduleId: ExpandableModuleId): void {
  expandedModule.value = expandedModule.value === moduleId ? null : moduleId;
}

watch(
  () => route.fullPath,
  () => {
    const nextView = resolveCurrentView(route);
    currentView.value = nextView;
    expandedModule.value = moduleByView[nextView] ?? null;
  },
  { immediate: true },
);

</script>

<style scoped>
.app-shell {
  min-height: 100vh;
  background: var(--color-bg);
  color: var(--color-text);
}

.app-shell__body {
  display: grid;
  grid-template-columns: var(--layout-shell-sidebar) minmax(0, 1fr);
  min-height: 100vh;
}

.app-shell__sidebar {
  position: sticky;
  top: 0;
  align-self: start;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
  border-right: 1px solid var(--color-divider);
}

.app-shell__sidebar-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 12px 10px;
  border-bottom: 1px solid var(--color-divider);
}

.app-shell__brand {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin-right: auto;
}

.app-shell__brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex: none;
  border-radius: 6px;
  background: var(--color-accent-800);
  color: var(--color-accent-200);
  font-size: 12px;
}

.app-shell__brand-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-heading);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--color-text);
}

.app-shell__gear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex: none;
  border: 1px solid var(--color-divider);
  border-radius: 8px;
  background: transparent;
  color: var(--color-neutral-400);
  font-size: 15px;
  cursor: pointer;
  text-decoration: none;
  transition: color 0.15s ease, border-color 0.15s ease;
}

.app-shell__gear:hover {
  color: var(--color-accent);
  border-color: var(--color-accent);
}

.app-shell__gear.is-disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.app-shell__sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 10px 8px;
  flex: 1;
  overflow: auto;
}

.app-shell__module {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.app-shell__link {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  min-height: 32px;
  padding: 5px 10px 5px 12px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: color-mix(in srgb, var(--color-text) 78%, transparent);
  font-family: var(--font-body);
  font-size: 13px;
  font-weight: 400;
  text-align: left;
  text-decoration: none;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.app-shell__link i.ph,
.app-shell__link i.ph-fill {
  width: 16px;
  flex: none;
  font-size: 16px;
  text-align: center;
}

.app-shell__link-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-shell__link-count {
  flex: none;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: var(--color-neutral-500);
}

.app-shell__link:hover {
  background: color-mix(in srgb, var(--color-text) 6%, transparent);
}

.app-shell__link.is-active {
  background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  color: var(--color-accent-200);
  font-weight: 500;
}

.app-shell__link-accent {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 15px;
  border-radius: 1px;
  background: var(--color-accent);
}

.app-shell__module-trigger {
  justify-content: flex-start;
}

.app-shell__module-chevron {
  flex: none;
  font-size: 13px;
  color: var(--color-neutral-500);
}

.app-shell__divider {
  height: 1px;
  margin: 9px 10px;
  background: var(--color-divider);
}

.app-shell__submenu {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 2px 0 6px 25px;
  padding-left: 9px;
  border-left: 1px solid var(--color-divider);
}

.app-shell__sublink {
  display: block;
  padding: 5px 8px;
  border-radius: 4px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
  text-decoration: none;
  transition: background 0.15s ease, color 0.15s ease;
}

.app-shell__sublink:hover {
  background: color-mix(in srgb, var(--color-text) 6%, transparent);
}

.app-shell__sublink.is-active {
  color: var(--color-accent-200);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
}

.app-shell__sidebar-footer {
  padding: 9px 10px;
  border-top: 1px solid var(--color-divider);
}

.app-shell__profile {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 5px 6px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  transition: background 0.15s ease;
}

.app-shell__profile:hover {
  background: color-mix(in srgb, var(--color-text) 6%, transparent);
}

.app-shell__profile-icon {
  flex: none;
  font-size: 22px;
  color: var(--color-neutral-500);
}

.app-shell__profile-text {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  line-height: 1.1;
  text-align: left;
}

.app-shell__profile-text strong,
.app-shell__profile-text small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-shell__profile-text strong {
  color: var(--color-text);
  font-size: 12.5px;
  font-weight: 500;
}

.app-shell__profile-text small {
  color: var(--color-neutral-500);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.app-shell__profile-caret {
  flex: none;
  font-size: 13px;
  color: var(--color-neutral-600);
}

.app-shell__main {
  min-width: 0;
  min-height: 100vh;
  padding: 0;
}

.app-shell__module-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  min-width: 0;
}

.app-shell__module-actions:empty {
  display: none;
}

.app-shell-submenu-enter-active,
.app-shell-submenu-leave-active {
  overflow: hidden;
  transition: max-height 0.2s ease, opacity 0.2s ease, transform 0.2s ease;
}

.app-shell-submenu-enter-from,
.app-shell-submenu-leave-to {
  max-height: 0;
  opacity: 0;
  transform: translateY(-4px);
}

.app-shell-submenu-enter-to,
.app-shell-submenu-leave-from {
  max-height: 240px;
  opacity: 1;
  transform: translateY(0);
}

@media (max-width: 960px) {
  .app-shell__body {
    grid-template-columns: 1fr;
  }

  .app-shell__sidebar {
    position: static;
    height: auto;
    border-right: none;
    border-bottom: 1px solid var(--color-divider);
  }
}
</style>
