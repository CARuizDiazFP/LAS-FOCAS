<!--
  Nombre de archivo: AppShell.vue
  Ubicación de archivo: web/frontend/src/components/app-shell/AppShell.vue
  Descripción: Shell unificado del SPA con header mínimo, sidebar modular y área de contenido
-->
<template>
  <div class="app-shell">
    <div class="app-shell__body">
      <aside class="app-shell__sidebar" aria-label="Navegación principal">
        <header class="app-shell__sidebar-header">
          <RouterLink
            v-if="isAdmin"
            class="app-shell__icon-action"
            to="/admin"
            title="Configuración"
            aria-label="Configuración"
          >
            <span aria-hidden="true">⚙</span>
          </RouterLink>
          <button
            v-else
            class="app-shell__icon-action is-disabled"
            type="button"
            title="Configuración no disponible"
            aria-label="Configuración no disponible"
            aria-disabled="true"
            disabled
          >
            <span aria-hidden="true">⚙</span>
          </button>

          <button class="app-shell__profile" type="button" :title="profileTooltip" aria-label="Perfil">
            <span class="app-shell__profile-icon" aria-hidden="true">👤</span>
            <span class="app-shell__profile-text">
              <strong>{{ profileName }}</strong>
              <small v-if="roleLabel">{{ roleLabel }}</small>
            </span>
          </button>
        </header>

        <nav class="app-shell__sidebar-nav">
          <RouterLink
            v-for="item in primaryLinks"
            :key="item.id"
            :to="item.to"
            :class="['app-shell__link', 'app-shell__link--root', { 'is-active': isSidebarLinkActive(item.id) }]"
          >
            <span class="app-shell__link-label">{{ item.label }}</span>
            <small v-if="item.description" class="app-shell__link-description">{{ item.description }}</small>
          </RouterLink>

          <section v-for="module in sidebarModules" :key="module.id" class="app-shell__module">
            <button
              type="button"
              :class="['app-shell__module-trigger', { 'is-active': isModuleActive(module.id) }]"
              :aria-controls="`submenu-${module.id}`"
              :aria-expanded="isModuleExpanded(module.id)"
              @click="toggleModule(module.id)"
            >
              <span class="app-shell__module-label">{{ module.label }}</span>
              <span
                :class="['app-shell__module-chevron', { 'is-open': isModuleExpanded(module.id) }]"
                aria-hidden="true"
              >></span>
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
                  :class="['app-shell__link', 'app-shell__link--sub', { 'is-active': isSidebarLinkActive(item.id) }]"
                >
                  <span class="app-shell__link-label">{{ item.label }}</span>
                </RouterLink>
              </div>
            </Transition>
          </section>
        </nav>
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
  | 'none';

type ExpandableModuleId = 'reportes' | 'dwdmCiena' | 'toolKit';

interface SidebarItem {
  id: Exclude<SidebarViewId, 'none'>;
  label: string;
  description?: string;
  to: RouteLocationRaw;
}

interface SidebarModule {
  id: ExpandableModuleId;
  label: string;
  items: SidebarItem[];
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
    description: 'Abre el Chat',
    to: { path: '/' },
  },
  {
    id: 'infraFo',
    label: 'Infraestructura FO',
    to: { path: '/infra' },
  },
  {
    id: 'servicios',
    label: 'Servicios 🌐',
    to: { path: '/servicios' },
  },
];

const sidebarModules: SidebarModule[] = [
  {
    id: 'reportes',
    label: 'Reportes',
    items: [
      { id: 'repetitividad', label: 'Repetitividad', to: { path: '/repetitividad' } },
      { id: 'sla', label: 'SLA', to: { path: '/sla' } },
      { id: 'historial', label: 'Historial', to: { path: '/reports-history' } },
    ],
  },
  {
    id: 'dwdmCiena',
    label: 'DWDM Ciena',
    items: [
      { id: 'alarmasCiena', label: 'Alarmas Ciena', to: { path: '/dwdm/ciena' } },
    ],
  },
  {
    id: 'toolKit',
    label: 'Tool Kit',
    items: [
      { id: 'comparadorVlans', label: 'Comparador de VLANs', to: { path: '/toolkit/vlan' } },
      { id: 'comparadorFo', label: 'Comparador FO', to: { path: '/fo' } },
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
  background: var(--color-bg-canvas);
  color: var(--color-text-primary);
}

.app-shell__icon-action,
.app-shell__profile {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  border: 1px solid var(--color-primary);
  background: var(--color-bg-panel);
  color: var(--color-text-primary);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}

.app-shell__icon-action {
  width: 40px;
  padding: 0;
  border-radius: var(--radius-pill);
  color: var(--color-primary);
  text-decoration: none;
  font-size: 1.1rem;
}

.app-shell__profile {
  flex: 1 1 auto;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  border-color: var(--color-border-default);
  border-radius: var(--radius-md);
  text-align: left;
}

.app-shell__icon-action:hover,
.app-shell__icon-action:focus-visible,
.app-shell__profile:hover,
.app-shell__profile:focus-visible {
  background: var(--color-brand-primary-soft);
  border-color: var(--color-primary);
  outline: none;
}

.app-shell__icon-action.is-disabled,
.app-shell__icon-action:disabled {
  border-color: var(--color-border-default);
  color: var(--color-text-muted);
  cursor: not-allowed;
}

.app-shell__profile-icon {
  flex: 0 0 auto;
}

.app-shell__profile-text {
  display: flex;
  min-width: 0;
  flex-direction: column;
  line-height: 1.1;
}

.app-shell__profile-text strong,
.app-shell__profile-text small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-shell__profile-text strong {
  color: var(--color-text-primary);
  font-size: 0.85rem;
}

.app-shell__profile-text small {
  color: var(--color-text-muted);
  font-size: 0.72rem;
}

.app-shell__body {
  display: grid;
  grid-template-columns: minmax(220px, var(--layout-shell-sidebar)) minmax(0, 1fr);
  min-height: 100vh;
}

.app-shell__sidebar {
  position: sticky;
  top: 0;
  align-self: start;
  height: 100vh;
  padding: 0 var(--space-4) var(--space-6);
  border-right: 1px solid var(--color-border-default);
  background: var(--color-bg-elevated);
}

.app-shell__sidebar-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: var(--layout-shell-topbar);
  margin: 0 calc(var(--space-4) * -1) var(--space-5);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-border-default);
  background: var(--color-bg-panel);
}

.app-shell__sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.app-shell__module {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.app-shell__link {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-lg);
  color: var(--color-text-primary);
  text-decoration: none;
  background: var(--color-bg-surface-alt);
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}

.app-shell__link--root {
  background: var(--color-bg-panel);
}

.app-shell__link--sub {
  min-height: 44px;
  margin-left: var(--space-4);
  padding-left: var(--space-5);
}

.app-shell__module-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 44px;
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-lg);
  background: var(--color-bg-panel);
  box-shadow: var(--shadow-card);
  color: var(--color-text-primary);
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}

.app-shell__module-trigger:hover,
.app-shell__module-trigger:focus-visible,
.app-shell__module-trigger.is-active,
.app-shell__link:hover,
.app-shell__link:focus-visible,
.app-shell__link.is-active {
  background: var(--color-brand-primary-soft);
  border-color: var(--color-primary);
  box-shadow: var(--shadow-focus);
  transform: translateX(2px);
  outline: none;
}

.app-shell__module-trigger:hover,
.app-shell__module-trigger:focus-visible,
.app-shell__module-trigger.is-active {
  transform: translateY(-1px);
}

.app-shell__module-label {
  font-size: 0.95rem;
  font-weight: 700;
  letter-spacing: 0.01em;
}

.app-shell__module-chevron {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  color: var(--color-text-muted);
  font-size: 1rem;
  line-height: 1;
  transition: transform 0.2s ease, color 0.2s ease;
}

.app-shell__module-chevron.is-open {
  color: var(--color-primary);
  transform: rotate(90deg);
}

.app-shell__submenu {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding-left: var(--space-2);
  border-left: 1px solid var(--color-border-default);
}

.app-shell__link-label {
  font-weight: 600;
}

.app-shell__link-description {
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.app-shell__main {
  min-width: 0;
  min-height: 100vh;
  padding: var(--space-4);
}

.app-shell__module-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  min-height: 0;
  min-width: 0;
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
    padding-top: 0;
    border-right: none;
    border-bottom: 1px solid var(--color-border-default);
  }

  .app-shell__sidebar-header {
    margin-bottom: var(--space-4);
  }

  .app-shell__main {
    padding: var(--space-4);
  }
}
</style>
