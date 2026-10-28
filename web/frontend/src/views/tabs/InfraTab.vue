<!--
  Nombre de archivo: InfraTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/InfraTab.vue
  Descripción: Tab de Infraestructura / Dashboard de Cámaras — migrado desde panel.js
-->
<template>
  <article class="infra-view">
    <!-- Toast container -->
    <teleport to="body">
      <div id="infra-toast-container" class="toast-container" aria-live="polite">
        <transition-group name="toast-anim">
          <div
            v-for="t in toasts"
            :key="t.id"
            :class="['toast', t.type]"
          >
            <span class="toast-icon">{{ toastIcon(t.type) }}</span>
            <div class="toast-content">
              <div class="toast-title">{{ t.title }}</div>
              <div v-if="t.message" class="toast-message">{{ t.message }}</div>
            </div>
            <button class="toast-close" @click="removeToast(t.id)">×</button>
          </div>
        </transition-group>
      </div>
    </teleport>

    <!-- Hidden file input para tracking upload -->
    <input ref="trackingFileInputEl" type="file" accept=".txt" style="display:none" @change="onArchivoElegido">

    <!-- Modal: Protocolo de Protección (ban) — Wizard 3 pasos -->
    <BaneoWizardModal
      ref="baneoWizardModal"
      :notificar="notificar"
      @baneo-creado="refrescarSiBuscado"
      @subir-tracking="elegirArchivo"
    />

    <!-- Modal: Resolución de tracking (flujo Portero 2 fases) -->
    <TrackingResolveModal
      ref="trackingResolveModal"
      :notificar="notificar"
      @tracking-resuelto="refrescarSiBuscado"
    />

    <!-- Modal: Baneos Activos (incluye el sub-modal Dar Aviso) -->
    <BaneosActivosModal
      ref="baneosActivosModal"
      :notificar="notificar"
      @baneo-levantado="refrescarSiBuscado"
      @cantidad-cambiada="n => (cantidadBaneosActivos = n)"
    />

    <!-- Modal: Limpiar servicio -->
    <LimpiarServicioModal
      ref="limpiarServicioModal"
      :notificar="notificar"
      @servicio-limpiado="refrescarSiBuscado"
    />

    <!-- Main content -->
    <div class="infra-panel">
      <header class="infra-header">
        <div>
          <span class="infra-kicker">Planta externa</span>
          <h1>Infraestructura FO</h1>
        </div>
        <div class="infra-toolbar-actions">
          <button class="btn danger" @click="openBanModal">
            <i class="ph ph-shield-warning" aria-hidden="true"></i>
            Protocolo Protección
          </button>
          <button class="btn subtle active-bans-btn" @click="openActiveBansModal">
            <i class="ph ph-lock-key" aria-hidden="true"></i>
            Baneos activos
            <span v-if="cantidadBaneosActivos > 0" class="active-bans-badge">{{ cantidadBaneosActivos }}</span>
          </button>
          <div
            class="btn subtle upload-drop-zone"
            :class="{ 'drag-over': isDragOver }"
            role="button"
            tabindex="0"
            @click="elegirArchivo"
            @keydown.enter.prevent="elegirArchivo"
            @keydown.space.prevent="elegirArchivo"
            @dragover.prevent="onDragOver"
            @dragenter.prevent="onDragEnter"
            @dragleave="onDragLeave"
            @drop.prevent="onDrop"
          >
            <i class="ph ph-folder-simple-plus" aria-hidden="true"></i>
            Subir tracking
          </div>
          <button class="btn subtle" @click="openLimpiarModal">
            <i class="ph ph-eraser" aria-hidden="true"></i>
            Limpiar servicio
          </button>
          <div class="download-dropdown-wrapper" ref="downloadDropdownEl">
            <button class="btn primary" @click.stop="toggleDownloadMenu">
              <i class="ph ph-download-simple" aria-hidden="true"></i>
              Descargar
              <i :class="['ph', 'ph-caret-down', 'dropdown-caret', { open: isDownloadMenuOpen }]" aria-hidden="true"></i>
            </button>
            <ul v-if="isDownloadMenuOpen" class="download-dropdown-menu" @click.stop>
              <li class="dropdown-item" @click="downloadCameras('xlsx', null)"><i class="ph ph-file-xls" aria-hidden="true"></i>Todas (XLSX)</li>
              <li class="dropdown-item" @click="downloadCameras('csv', null)"><i class="ph ph-file-csv" aria-hidden="true"></i>Todas (CSV)</li>
              <li class="dropdown-divider"></li>
              <li class="dropdown-item" @click="downloadCameras('xlsx', 'BANEADA')"><span class="infra-legend-dot baneada"></span>Solo Baneadas</li>
              <li class="dropdown-item" @click="downloadCameras('xlsx', 'OCUPADA')"><span class="infra-legend-dot ocupada"></span>Con Ingreso</li>
            </ul>
          </div>
        </div>
      </header>

      <hr class="noc-rule" />

      <div class="infra-search-area">
        <div class="fop-search-row">
          <div class="fop-search-input">
            <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
            <input
              v-model="searchInput"
              type="text"
              placeholder="Buscar por nombre, dirección, servicio…"
              @keydown.enter="addTerm"
            />
          </div>
          <button class="btn subtle" @click="addTerm">Agregar término</button>
          <button class="btn primary" :disabled="loading" @click="runSearch">
            <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
            Buscar
          </button>
          <button class="btn infra-btn-ghost" @click="clearAll">Limpiar</button>
        </div>

        <div class="infra-chips-row">
          <span v-if="searchTerms.length" class="fop-search-terms">
            <span v-for="(term, i) in searchTerms" :key="i" class="fop-search-term">
              <span class="fop-search-term-value">{{ term }}</span>
              <button class="fop-search-term-remove" @click="removeTerm(i)">×</button>
            </span>
          </span>

          <span v-if="searchTerms.length" class="infra-chips-separator" aria-hidden="true"></span>

          <button
            v-for="item in legendItems"
            :key="item.estado"
            type="button"
            :class="['infra-legend-item', { active: activeStateFilter === item.estado }]"
            @click="toggleStateFilter(item.estado)"
          >
            <span :class="['infra-legend-dot', item.dotClass]"></span>
            {{ item.estado }}
            <span class="infra-legend-count">{{ legendCounts[item.estado] ?? 0 }}</span>
          </button>

          <span class="infra-count">
            <strong>{{ camaras.length }}</strong> cámaras
          </span>

          <label class="infra-toggle-no-operativas">
            <input type="checkbox" v-model="incluirNoOperativas" @change="onToggleIncluirNoOperativas" />
            Mostrar No operativas
          </label>
        </div>

        <div v-if="statusText" :class="['fop-status', statusVariant]">{{ statusText }}</div>
      </div>

      <div v-if="loading" class="infra-state-box">
        <i class="ph ph-circle-notch infra-spin" aria-hidden="true"></i>
        Buscando...
      </div>
      <div v-else-if="!hasSearched" class="infra-state-box">
        <i class="ph ph-circle-notch infra-spin" aria-hidden="true"></i>
        Cargando cámaras...
      </div>
      <div v-else-if="camaras.length === 0" class="infra-state-box">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <p>Sin resultados.</p>
      </div>
      <div v-else class="fop-grid">
        <article
          v-for="camara in camaras"
          :key="camara.id as string"
          class="fop-camara-card"
          :data-estado="camara.estado ?? 'LIBRE'"
          :data-inconsistente="camara.inconsistente ? 'true' : 'false'"
        >
          <div class="infra-camara-row">
            <span :class="['infra-camara-dot', estadoDotClass(camara.estado)]" aria-hidden="true"></span>
            <span class="infra-camara-estado-text">{{ camara.estado || 'LIBRE' }}</span>
            <span v-if="camara.id != null" class="fop-camara-id">{{ camaraIdLabel(camara) }}</span>
          </div>

          <h3 class="fop-camara-nombre">{{ camara.nombre || camara.direccion || 'Sin nombre' }}</h3>

          <div class="infra-camara-hairline"></div>

          <div class="infra-camara-row">
            <span class="fop-camara-meta">{{ camaraMeta(camara) }}</span>
            <RouterLink
              v-if="camara.id != null"
              class="fop-edit-btn"
              :to="`/infra/Camaras/${camara.id}`"
            >Detalle</RouterLink>
          </div>
        </article>
      </div>

      <div v-if="!loading && hasSearched && total > PAGE_SIZE" class="infra-pagination">
        <button class="btn subtle" type="button" :disabled="offset === 0" @click="prevPage">‹ Anterior</button>
        <span class="infra-pagination-info">
          Página {{ Math.floor(offset / PAGE_SIZE) + 1 }} de {{ Math.max(1, Math.ceil(total / PAGE_SIZE)) }}
        </span>
        <button class="btn subtle" type="button" :disabled="offset + PAGE_SIZE >= total" @click="nextPage">Siguiente ›</button>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { exportarCamaras } from '../../api/infra';
import type { Notificar } from '../../composables/infra/tipos';
import { useInfraBusqueda } from '../../composables/infra/useInfraBusqueda';
import { useTrackingAnalisis } from '../../composables/infra/useTrackingAnalisis';
import BaneoWizardModal from '../../components/infra/infratab/BaneoWizardModal.vue';
import TrackingResolveModal from '../../components/infra/infratab/TrackingResolveModal.vue';
import BaneosActivosModal from '../../components/infra/infratab/BaneosActivosModal.vue';
import LimpiarServicioModal from '../../components/infra/infratab/LimpiarServicioModal.vue';

// --- Toast ---
interface Toast { id: number; type: string; title: string; message?: string }
const toasts = ref<Toast[]>([]);
let _toastId = 0;
function showToast(type: string, title: string, message?: string, duration = 5000) {
  const id = ++_toastId;
  toasts.value.push({ id, type, title, message });
  if (duration > 0) setTimeout(() => removeToast(id), duration);
}
function removeToast(id: number) {
  const i = toasts.value.findIndex(t => t.id === id);
  if (i !== -1) toasts.value.splice(i, 1);
}
function toastIcon(type: string) {
  return { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' }[type] ?? 'ℹ';
}
const notificar: Notificar = (tipo, titulo, mensaje) => showToast(tipo, titulo, mensaje);

// --- Búsqueda (useInfraBusqueda) ---
const {
  PAGE_SIZE,
  searchInput,
  searchTerms,
  camaras,
  loading,
  hasSearched,
  statusText,
  statusVariant,
  offset,
  total,
  activeStateFilter,
  incluirNoOperativas,
  legendItems,
  legendCounts,
  addTerm,
  removeTerm,
  clearAll,
  onToggleIncluirNoOperativas,
  toggleStateFilter,
  estadoDotClass,
  camaraMeta,
  camaraIdLabel,
  runSearch,
  nextPage,
  prevPage,
  refrescarSiBuscado,
} = useInfraBusqueda(notificar);

onMounted(() => {
  void runSearch();
});

// --- Protocolo de Protección (ban) — Wizard 3 pasos ---
const baneoWizardModal = ref<InstanceType<typeof BaneoWizardModal> | null>(null);
function openBanModal() {
  baneoWizardModal.value?.abrir();
}

// --- Baneos Activos (incluye el sub-modal Dar Aviso) ---
const baneosActivosModal = ref<InstanceType<typeof BaneosActivosModal> | null>(null);
// Badge del botón: se actualiza con cada carga del modal (como antes, no se consulta al montar).
const cantidadBaneosActivos = ref(0);
function openActiveBansModal() {
  baneosActivosModal.value?.abrir();
}

// --- Upload Tracking (flujo Portero 2 fases): elección del archivo; el análisis y la resolución
// viven en TrackingResolveModal ---
const trackingResolveModal = ref<InstanceType<typeof TrackingResolveModal> | null>(null);

const {
  trackingFileInputEl,
  isDragOver,
  elegirArchivo,
  onDragOver,
  onDragEnter,
  onDragLeave,
  onDrop,
  onArchivoElegido,
} = useTrackingAnalisis(notificar, (contenido, nombre) => trackingResolveModal.value?.abrir(contenido, nombre));

// --- Limpiar servicio ---
const limpiarServicioModal = ref<InstanceType<typeof LimpiarServicioModal> | null>(null);
function openLimpiarModal() {
  limpiarServicioModal.value?.abrir();
}

// --- Descargar: dropdown de exportación ---
const downloadDropdownEl = ref<HTMLElement | null>(null);
const isDownloadMenuOpen = ref(false);

function toggleDownloadMenu() {
  isDownloadMenuOpen.value = !isDownloadMenuOpen.value;
}

function _closeDownloadMenu(e: MouseEvent) {
  if (downloadDropdownEl.value && !downloadDropdownEl.value.contains(e.target as Node)) {
    isDownloadMenuOpen.value = false;
  }
}

onMounted(() => document.addEventListener('click', _closeDownloadMenu));
onUnmounted(() => document.removeEventListener('click', _closeDownloadMenu));

async function downloadCameras(format: 'xlsx' | 'csv', filterStatus: string | null) {
  isDownloadMenuOpen.value = false;
  const params = new URLSearchParams({ format });
  if (filterStatus) params.set('filter_status', filterStatus);
  if (!filterStatus && searchTerms.value.length === 1 && /^\d+$/.test(searchTerms.value[0].trim())) {
    params.set('servicio_id', searchTerms.value[0].trim());
  }
  const filterLabel = filterStatus ? ` (${filterStatus})` : '';
  showToast('info', 'Preparando descarga...', `Exportando cámaras${filterLabel} en ${format.toUpperCase()}`);
  try {
    const filename = await exportarCamaras(params);
    showToast('success', 'Descarga completa', filename);
  } catch (e: unknown) {
    showToast('error', 'Error al descargar', e instanceof Error ? e.message : String(e));
  }
}
</script>

<style scoped>
.infra-view { display: flex; flex-direction: column; height: 100%; overflow: hidden; background: var(--color-bg); }
.infra-panel { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
.infra-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 22px 0 0; flex-wrap: wrap; }
.infra-kicker { font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--color-accent); }
.infra-header h1 { font-size: 27px; margin: 3px 0 0; }

.infra-search-area { padding: 15px 0 14px; display: flex; flex-direction: column; gap: 11px; }
.fop-search-row { display: flex; gap: 8px; flex-wrap: wrap; }
.fop-search-input { position: relative; flex: 1; min-width: 220px; }
.fop-search-input i { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); color: var(--color-neutral-500); font-size: 15px; pointer-events: none; }
.fop-search-input input {
  width: 100%; min-height: 38px; padding: 6px 10px 6px 33px; font-size: 14px;
  background: var(--color-surface); border: 1px solid var(--color-divider); border-radius: var(--radius-md);
  color: var(--color-text); caret-color: var(--color-accent);
}
.fop-search-input input:focus-visible { border-color: var(--color-accent); outline-offset: 0; }
.infra-btn-ghost { color: var(--color-accent); padding-inline: 2.8px; background: transparent; }
.infra-btn-ghost:hover { background: transparent; text-decoration: underline; }

.infra-chips-row { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.fop-search-terms { display: inline-flex; flex-wrap: wrap; gap: 6px; }
.fop-search-term {
  display: inline-flex; align-items: center; gap: 4px;
  background: color-mix(in srgb, var(--color-accent) 12%, transparent); color: var(--color-accent-200);
  border: 1px solid var(--color-accent); border-radius: var(--radius-pill);
  padding: 3px 6px 3px 10px; font-size: 11.5px;
}
.fop-search-term-remove { background: none; border: none; cursor: pointer; color: inherit; padding: 0; line-height: 1; }
.infra-chips-separator { width: 1px; height: 15px; background: var(--color-divider); }
.infra-count { margin-left: auto; font-size: 12px; font-variant-numeric: tabular-nums; color: color-mix(in srgb, var(--color-text) 55%, transparent); white-space: nowrap; }
.infra-count strong { color: var(--color-text); font-weight: 500; }
.infra-toggle-no-operativas { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: color-mix(in srgb, var(--color-text) 65%, transparent); cursor: pointer; user-select: none; white-space: nowrap; }
.infra-toggle-no-operativas input { accent-color: var(--color-accent); }
.fop-status { font-size: 12.5px; color: color-mix(in srgb, var(--color-text) 55%, transparent); }
.fop-status.error { color: var(--color-state-error); }
.fop-status.success { color: var(--color-state-ok); }

.infra-state-box {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  max-width: 260px; margin: 34px auto; padding: 34px 22px;
  text-align: center; color: color-mix(in srgb, var(--color-text) 48%, transparent); font-size: 12.5px;
}
.infra-state-box i { font-size: 26px; color: var(--color-neutral-600); }
.infra-state-box p { margin: 0; }
.infra-spin { animation: spin 1s linear infinite; }

.fop-grid {
  flex: 1; min-height: 0; overflow: auto;
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 11px;
  padding: 12px 0 30px;
}
@media (max-width: 1280px) { .fop-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1024px) { .fop-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .fop-grid { grid-template-columns: 1fr; } }

.infra-pagination {
  display: flex; align-items: center; justify-content: center; gap: 14px;
  padding: 4px 0 16px; flex-shrink: 0;
}
.infra-pagination-info {
  font-size: 12.5px; font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.fop-camara-card {
  display: flex; flex-direction: column; gap: 9px;
  padding: 12px 13px 11px; border-radius: var(--radius-md);
  background: var(--color-surface); box-shadow: var(--shadow-sm);
  transition: box-shadow 0.15s ease;
}
.fop-camara-card:hover { box-shadow: 0 0 0 1px var(--color-accent), var(--shadow-md); }
.infra-camara-row { display: flex; align-items: center; gap: 7px; }
.infra-camara-dot { width: 7px; height: 7px; flex: none; border-radius: 50%; background: var(--color-state-idle); }
.infra-camara-dot.libre { background: var(--color-state-ok); }
.infra-camara-dot.ocupada { background: var(--color-state-warn); }
.infra-camara-dot.baneada { background: var(--color-state-error); }
.infra-camara-dot.no_operativa { background: var(--color-state-idle); }
.infra-camara-estado-text {
  font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}
.fop-camara-id { margin-left: auto; font-size: 10.5px; font-variant-numeric: tabular-nums; color: var(--color-neutral-500); }
.fop-camara-nombre {
  margin: 0; min-height: 36px; font-size: 14.5px; font-weight: 500; line-height: 1.25;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.infra-camara-hairline { height: 1px; background: var(--color-divider); }
.fop-camara-meta {
  font-size: 10.5px; color: color-mix(in srgb, var(--color-text) 48%, transparent);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.fop-edit-btn {
  margin-left: auto; flex: none; padding: 3px 9px; border: 1px solid var(--color-accent);
  border-radius: 4px; font-family: var(--font-heading); font-size: 11px; font-weight: 500;
  color: var(--color-accent); text-decoration: none;
}
/* Modal */
.camera-state-modal, .tracking-detail-modal { position: fixed; inset: 0; margin: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--color-surface); color: var(--text); padding: 24px; max-width: 520px; width: 95vw; max-height: 90vh; overflow-y: auto; }
.camera-state-modal::backdrop, .tracking-detail-modal::backdrop { background: rgba(0,0,0,.6); }
.camera-state-title-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.camera-state-meta-row { display: flex; gap: 16px; flex-wrap: wrap; font-size: .85rem; margin-bottom: 8px; color: var(--muted); }
.camera-state-badge { padding: 2px 8px; border-radius: 10px; font-size: .75rem; }
.camera-state-badge.ok { background: color-mix(in srgb, var(--color-state-ok) 15%, transparent); color: var(--color-state-ok); }
.camera-state-badge.warning { background: color-mix(in srgb, var(--color-state-warn) 15%, transparent); color: var(--color-state-warn); }
.camera-state-incidents { margin: 12px 0; }
.camera-state-incidents-title { font-size: .8rem; font-weight: 600; color: var(--muted); margin-bottom: 6px; }
.camera-state-incident-item { font-size: .82rem; padding: 6px 0; border-bottom: 1px solid var(--border); display: flex; gap: 12px; flex-wrap: wrap; }
.camera-state-empty { font-size: .82rem; color: var(--muted); margin: 8px 0; }
.camera-state-select { width: 100%; margin: 8px 0 14px; }
.camera-state-actions { display: flex; gap: 8px; margin-top: 14px; }
/* Tracking modal */
.tracking-detail-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.tracking-detail-title { margin: 0; font-size: 1rem; flex: 1; }
.tracking-detail-close { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.3rem; }
.tracking-download-btn { font-size: .78rem; padding: 4px 10px; background: color-mix(in srgb, var(--color-text) 7%, transparent); border: 1px solid var(--border); border-radius: 6px; cursor: pointer; color: var(--text); }
.tracking-rutas-tabs { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.tracking-ruta-tab { padding: 5px 12px; border-radius: 14px; font-size: .8rem; border: 1px solid var(--border); background: none; cursor: pointer; color: var(--text); }
.tracking-ruta-tab.active { background: var(--tab-color, var(--color-accent)); color: var(--color-neutral-100); border-color: transparent; }
.tracking-sequence { display: flex; flex-direction: column; gap: 6px; }
.tracking-item { display: flex; align-items: flex-start; gap: 8px; font-size: .85rem; padding: 6px 0; border-bottom: 1px solid var(--border); }
.tracking-punta { color: var(--color-accent); }
.tracking-punta-label { font-size: .72rem; color: var(--muted); display: block; }
.tracking-cable { flex-direction: column; gap: 2px; }
.tracking-cable-name { font-weight: 600; }
.tracking-atenuacion { color: var(--color-state-warn); font-size: .78rem; }
.tracking-empalme-id { color: var(--muted); font-size: .75rem; }
.tracking-loading, .tracking-error, .tracking-empty { padding: 16px; color: var(--muted); font-size: .85rem; }
.tracking-error { color: var(--color-state-error); }
/* Toasts */
.toast-container { position: fixed; bottom: 24px; right: 24px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; pointer-events: none; }
.toast { display: flex; align-items: flex-start; gap: 10px; background: var(--color-surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; min-width: 260px; max-width: 380px; pointer-events: all; box-shadow: 0 4px 12px rgba(0,0,0,.4); }
.toast.success { border-left: 3px solid var(--color-state-ok); }
.toast.error { border-left: 3px solid var(--color-state-error); }
.toast.warning { border-left: 3px solid var(--color-state-warn); }
.toast.info { border-left: 3px solid var(--color-accent); }
.toast-icon { font-size: 1rem; line-height: 1; }
.toast-content { flex: 1; }
.toast-title { font-weight: 600; font-size: .88rem; }
.toast-message { font-size: .82rem; color: var(--muted); margin-top: 2px; }
.toast-close { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 1.1rem; padding: 0; }
.toast-anim-enter-active, .toast-anim-leave-active { transition: all .25s ease; }
.toast-anim-enter-from, .toast-anim-leave-to { opacity: 0; transform: translateX(24px); }

/* Toolbar */
.infra-toolbar-actions { display: flex; gap: 7px; flex-wrap: wrap; align-items: center; }
.infra-toolbar-actions .btn { min-height: 34px; font-size: 12.5px; }

/* Zona Drag & Drop de upload tracking (reusa el look de .btn.subtle) */
.upload-drop-zone.drag-over {
  border-color: var(--color-accent); color: var(--color-accent);
}

/* Botones extra (modificadores de .btn global) */
.btn.danger { background: transparent; color: oklch(0.72 0.11 25); border: 1px solid color-mix(in srgb, var(--color-state-error) 50%, transparent); }
.btn.danger:hover:not(:disabled) { background: color-mix(in srgb, var(--color-state-error) 12%, transparent); }
.btn.danger-subtle { background: transparent; color: var(--color-state-error); border: 1px solid color-mix(in srgb, var(--color-state-error) 20%, transparent); }
.btn.danger-subtle:hover:not(:disabled) { background: color-mix(in srgb, var(--color-state-error) 10%, transparent); }

/* Dropdown descargar */
.download-dropdown-wrapper { position: relative; }
.dropdown-caret { display: inline-block; transition: transform .2s; font-size: .75rem; margin-left: 2px; }
.dropdown-caret.open { transform: rotate(180deg); }
.download-dropdown-menu {
  position: absolute; top: calc(100% + 4px); right: 0; z-index: 200;
  min-width: 180px; margin: 0; padding: 4px 0; list-style: none;
  background: var(--color-surface); border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 6px 18px rgba(0,0,0,.45);
}
.dropdown-item {
  padding: 9px 14px; font-size: .85rem; cursor: pointer;
  color: var(--text); display: flex; align-items: center; gap: 7px; white-space: nowrap;
}
.dropdown-item:hover { background: color-mix(in srgb, var(--color-text) 7%, transparent); }
.dropdown-divider { border: none; border-top: 1px solid var(--border); margin: 4px 0; }

/* Leyenda de estados — fusionada como chips de filtro */
.infra-legend-item {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: var(--radius-pill); font-size: 11.5px; cursor: pointer;
  border: 1px solid var(--color-divider); background: transparent;
  color: color-mix(in srgb, var(--color-text) 66%, transparent);
}
.infra-legend-item:hover { border-color: var(--color-accent); }
.infra-legend-item.active {
  border-color: var(--color-accent); background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}
.infra-legend-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; flex-shrink: 0; }
.infra-legend-dot.libre { background: var(--color-state-ok); }
.infra-legend-dot.ocupada { background: var(--color-state-warn); }
.infra-legend-dot.baneada { background: var(--color-state-error); }
.infra-legend-dot.no_operativa { background: var(--color-state-idle); }
.infra-legend-count { font-variant-numeric: tabular-nums; color: color-mix(in srgb, var(--color-text) 42%, transparent); }

/* ─── Baneos Activos ─── */
.active-bans-btn { position: relative; }
.active-bans-badge {
  position: absolute; top: -6px; right: -6px;
  min-width: 18px; height: 18px; border-radius: 9px; padding: 0 4px;
  background: var(--color-state-error); color: var(--color-neutral-100); font-size: .72rem; font-weight: 700;
  display: inline-flex; align-items: center; justify-content: center; line-height: 1;
}
</style>
