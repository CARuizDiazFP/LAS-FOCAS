<!--
  Nombre de archivo: AdminCamarasViewer.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminCamarasViewer.vue
  Descripción: Dashboard /admin/servicios/viewer/Camaras — listado dual grid/lista de Cámaras raíz y detección de duplicados por nombre normalizado
-->
<template>
  <section class="camaras-viewer">
    <AdminPageHeader
      kicker="Panel admin · Viewer"
      title="Cámaras"
      subtitle="Listado de Cámaras raíz y detección de candidatas a duplicado por nombre."
    />

    <div class="camaras-viewer__toolbar">
      <div class="camaras-viewer__toolbar-row">
        <template v-if="!soloDuplicados">
          <div class="camaras-viewer__search">
            <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
            <input v-model="query" type="search" placeholder="Buscar por nombre" @input="onSearchInput" />
          </div>

          <div class="camaras-viewer__view-toggle" role="radiogroup" aria-label="Tipo de vista">
            <button
              type="button"
              role="radio"
              :aria-checked="vista === 'grid'"
              :class="['camaras-viewer__view-option', { 'is-active': vista === 'grid' }]"
              title="Vista grilla"
              @click="setVista('grid')"
            >
              <i class="ph ph-squares-four" aria-hidden="true"></i>
            </button>
            <button
              type="button"
              role="radio"
              :aria-checked="vista === 'list'"
              :class="['camaras-viewer__view-option', { 'is-active': vista === 'list' }]"
              title="Vista lista"
              @click="setVista('list')"
            >
              <i class="ph ph-rows" aria-hidden="true"></i>
            </button>
          </div>
        </template>

        <button
          type="button"
          :class="['camaras-viewer__chip', 'camaras-viewer__chip--duplicadas', { 'is-active': soloDuplicados }]"
          @click="toggleSoloDuplicados"
        >
          <i class="ph ph-copy" aria-hidden="true"></i>
          Sólo duplicadas
        </button>

        <button class="btn primary" type="button" :disabled="loading || loadingGrupos" @click="refrescar">
          <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
          Actualizar
        </button>

        <button
          v-if="soloDuplicados"
          class="btn subtle"
          type="button"
          :disabled="loadingGrupos || grupos.length === 0"
          @click="abrirFusionMasiva"
        >
          <i class="ph ph-stack" aria-hidden="true"></i>
          Fusión masiva
        </button>
      </div>

      <div v-if="!soloDuplicados" class="camaras-viewer__toolbar-row camaras-viewer__chips-row">
        <span class="camaras-viewer__chips-label">Estado</span>
        <button
          v-for="chip in estadoChips"
          :key="chip.value"
          type="button"
          :class="['camaras-viewer__chip', { 'is-active': filtroEstado === chip.value }]"
          @click="setEstado(chip.value)"
        >
          <span :class="['camaras-viewer__chip-dot', `is-${chip.token}`]" aria-hidden="true"></span>
          {{ chip.label }}
        </button>
        <span class="camaras-viewer__count">
          <strong>{{ total.toLocaleString('es-AR') }}</strong> cámaras raíz · mostrando {{ items.length }}
        </span>
      </div>

      <div v-else class="camaras-viewer__toolbar-row">
        <span class="camaras-viewer__count">
          <strong>{{ grupos.length }}</strong> grupo{{ grupos.length !== 1 ? 's' : '' }} candidato{{ grupos.length !== 1 ? 's' : '' }} a duplicado
        </span>
      </div>
    </div>

    <div v-if="error" class="camaras-viewer__inline-error">{{ error }}</div>

    <!-- Vista dual (listado general): grid/lista con scroll infinito -->
    <div v-if="!soloDuplicados" ref="scrollEl" class="camaras-viewer__scroll">
      <template v-if="items.length > 0">
        <div v-if="vista === 'grid'" class="camaras-viewer__grid">
          <CamaraViewerCard v-for="item in items" :key="item.id" :camara="item" />
        </div>

        <div v-else class="camaras-viewer__list-layout">
          <div class="camaras-viewer__list">
            <div
              v-for="item in items"
              :key="item.id"
              role="button"
              tabindex="0"
              :class="['camaras-viewer__list-row', { 'is-selected': item.id === selectedId }]"
              @click="selectedId = item.id"
              @keyup.enter="selectedId = item.id"
            >
              <span :class="['camaras-viewer__list-dot', `is-${estadoCamaraToken(item.estado)}`]" aria-hidden="true"></span>
              <span class="camaras-viewer__list-nombre">{{ item.nombre || `Cámara ${item.id}` }}</span>
              <span class="camaras-viewer__list-stat">{{ item.botellas_count }} bot.</span>
              <span class="camaras-viewer__list-stat">{{ item.cables_count }} cbl.</span>
              <span class="camaras-viewer__list-estado">{{ item.estado }}</span>
            </div>
          </div>

          <aside v-if="selectedItem" class="camaras-viewer__preview">
            <span class="camaras-viewer__preview-kicker">Vista previa</span>
            <h2 class="camaras-viewer__preview-title">{{ selectedItem.nombre || `Cámara ${selectedItem.id}` }}</h2>
            <div class="camaras-viewer__preview-tags">
              <span class="camaras-viewer__preview-tag is-accent">{{ selectedItem.estado }}</span>
              <span class="camaras-viewer__preview-tag">ID {{ selectedItem.id }}</span>
            </div>
            <div class="camaras-viewer__preview-stats">
              <div class="camaras-viewer__preview-stat">
                <span class="camaras-viewer__preview-label">Botellas</span>
                <strong>{{ selectedItem.botellas_count }}</strong>
              </div>
              <div class="camaras-viewer__preview-stat">
                <span class="camaras-viewer__preview-label">Cables</span>
                <strong>{{ selectedItem.cables_count }}</strong>
              </div>
            </div>
            <RouterLink class="btn primary" :to="`/infra/Camaras/${selectedItem.id}`">
              Abrir detalle completo
              <i class="ph ph-arrow-right" aria-hidden="true"></i>
            </RouterLink>
          </aside>
        </div>
      </template>

      <div v-else-if="!loading" class="camaras-viewer__state-box">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <h3>Ninguna cámara coincide</h3>
        <p>Probá con otro nombre o quitá el filtro de estado.</p>
      </div>

      <div v-if="loading && items.length > 0" class="camaras-viewer__loading-more">
        <i class="ph ph-circle-notch camaras-viewer__spin" aria-hidden="true"></i>
        Cargando más cámaras...
      </div>

      <div ref="sentinel" class="camaras-viewer__sentinel" aria-hidden="true"></div>
    </div>

    <!-- Vista de duplicadas: tarjeta por grupo -->
    <div v-else class="camaras-viewer__scroll">
      <div v-if="loadingGrupos" class="camaras-viewer__state-box">
        <i class="ph ph-circle-notch camaras-viewer__spin" aria-hidden="true"></i>
        <h3>Calculando grupos...</h3>
      </div>

      <div v-else-if="errorGrupos" class="camaras-viewer__state-box is-error">
        <i class="ph ph-warning-circle" aria-hidden="true"></i>
        <h3>No se pudo calcular los duplicados</h3>
        <p>{{ errorGrupos }}</p>
      </div>

      <div v-else-if="grupos.length === 0" class="camaras-viewer__state-box">
        <i class="ph ph-check-circle" aria-hidden="true"></i>
        <h3>Sin candidatas a duplicado</h3>
        <p>No se detectaron grupos por normalización extendida de nombre.</p>
      </div>

      <div v-else class="camaras-viewer__grupos">
        <article v-for="grupo in grupos" :key="grupo.clave_normalizada" class="camaras-viewer__grupo-card">
          <header class="camaras-viewer__grupo-header">
            <span>{{ grupo.miembros.length }} cámaras candidatas</span>
            <span v-if="grupo.estados_en_conflicto" class="camaras-viewer__grupo-badge">
              <i class="ph ph-warning" aria-hidden="true"></i>
              Estados distintos
            </span>
            <button class="btn subtle camaras-viewer__grupo-fusionar-todas" type="button" @click="abrirFusionGrupo(grupo)">
              <i class="ph ph-git-merge" aria-hidden="true"></i>
              Fusionar todas
            </button>
          </header>
          <div class="camaras-viewer__grupo-miembros">
            <CamaraViewerCard
              v-for="miembro in grupo.miembros"
              :key="miembro.id"
              :camara="miembro"
              :mostrar-fusionar="true"
              @fusionar="abrirFusion(grupo, $event)"
            />
          </div>
        </article>
      </div>
    </div>

    <ModalUnificarCamara
      :open="modalOpen"
      :camara-id="modalCamaraId"
      :camara-nombre="modalCamaraNombre"
      :sugerencia-inicial="modalSugerencia"
      @close="modalOpen = false"
      @merged="handleMerged"
      @error="handleModalError"
    />

    <ModalFusionarGrupo
      :open="modalGrupoOpen"
      :grupo="modalGrupoSeleccionado"
      @close="modalGrupoOpen = false"
      @merged="handleMerged"
      @error="handleModalError"
    />

    <ModalConfirmarAccionMasiva
      :open="modalMasivaOpen"
      titulo="Fusión masiva de Cámaras duplicadas"
      :mensaje="mensajeFusionMasiva"
      :confirmando="confirmandoMasiva"
      :error="errorMasiva"
      :resultado="resultadoMasiva"
      @close="modalMasivaOpen = false"
      @confirm="confirmarFusionMasiva"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';

import AdminPageHeader from '../components/AdminPageHeader.vue';
import ModalFusionarGrupo from '../../components/infra/ModalFusionarGrupo.vue';
import ModalConfirmarAccionMasiva from '../../components/infra/ModalConfirmarAccionMasiva.vue';
import CamaraViewerCard from '../../components/infra/CamaraViewerCard.vue';
import ModalUnificarCamara from '../../components/infra/ModalUnificarCamara.vue';
import {
  estadoCamaraToken,
  getCamarasDuplicados,
  mergeMasivoCamaras,
  searchCamarasViewer,
  type CamaraViewerItem,
  type GrupoCamarasDuplicadas,
} from '../../api/camaras';

const LIMIT = 60;
const VISTA_STORAGE_KEY = 'camaras-viewer.vista';

const query = ref('');
const items = ref<CamaraViewerItem[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref('');
const offset = ref(0);
const hasMore = ref(true);
const sentinel = ref<HTMLElement | null>(null);
const scrollEl = ref<HTMLElement | null>(null);
const filtroEstado = ref('');
const selectedId = ref<number | null>(null);

const soloDuplicados = ref(false);
const grupos = ref<GrupoCamarasDuplicadas[]>([]);
const loadingGrupos = ref(false);
const errorGrupos = ref('');

const modalOpen = ref(false);
const modalCamaraId = ref<number | null>(null);
const modalCamaraNombre = ref('');
const modalSugerencia = ref('');

const modalGrupoOpen = ref(false);
const modalGrupoSeleccionado = ref<GrupoCamarasDuplicadas | null>(null);

const modalMasivaOpen = ref(false);
const confirmandoMasiva = ref(false);
const errorMasiva = ref('');
const resultadoMasiva = ref<string | null>(null);
const mensajeFusionMasiva = computed(
  () =>
    `Esto fusionará automáticamente los ${grupos.value.length} grupos detectados: para cada uno se ` +
    'conservará la Cámara con más botellas y cables (empate: id más bajo) y las demás se eliminarán ' +
    'físicamente tras heredar todo lo heredable. Esta acción no se puede deshacer.',
);

const vista = ref<'grid' | 'list'>(
  (localStorage.getItem(VISTA_STORAGE_KEY) as 'grid' | 'list' | null) === 'list' ? 'list' : 'grid',
);

const estadoChips = [
  { label: 'Libre', value: 'LIBRE', token: 'ok' as const },
  { label: 'Ocupada', value: 'OCUPADA', token: 'warn' as const },
  { label: 'Baneada', value: 'BANEADA', token: 'error' as const },
  { label: 'No operativa', value: 'NO_OPERATIVA', token: 'idle' as const },
];

const selectedItem = computed(
  () => items.value.find((item) => item.id === selectedId.value) ?? items.value[0] ?? null,
);

let observer: IntersectionObserver | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function mergeItems(next: CamaraViewerItem[]): void {
  const seen = new Set(items.value.map((item) => item.id));
  for (const item of next) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    items.value.push(item);
  }
}

async function loadNextPage(): Promise<void> {
  if (loading.value || !hasMore.value) return;
  loading.value = true;
  error.value = '';
  try {
    const response = await searchCamarasViewer({
      q: query.value.trim(),
      estado: filtroEstado.value,
      limit: LIMIT,
      offset: offset.value,
    });
    total.value = response.total;
    mergeItems(response.camaras);
    offset.value += response.camaras.length;
    hasMore.value = response.camaras.length === LIMIT && offset.value < response.total;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo consultar cámaras';
  } finally {
    loading.value = false;
  }
}

async function reloadFromZero(): Promise<void> {
  items.value = [];
  total.value = 0;
  offset.value = 0;
  hasMore.value = true;
  await loadNextPage();
}

async function reloadDuplicados(): Promise<void> {
  loadingGrupos.value = true;
  errorGrupos.value = '';
  try {
    const response = await getCamarasDuplicados();
    grupos.value = response.grupos;
  } catch (err: unknown) {
    errorGrupos.value = err instanceof Error ? err.message : 'No se pudo calcular los grupos de duplicados';
  } finally {
    loadingGrupos.value = false;
  }
}

function onSearchInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => void reloadFromZero(), 320);
}

function setEstado(value: string): void {
  filtroEstado.value = filtroEstado.value === value ? '' : value;
  void reloadFromZero();
}

function setVista(next: 'grid' | 'list'): void {
  vista.value = next;
  localStorage.setItem(VISTA_STORAGE_KEY, next);
}

function toggleSoloDuplicados(): void {
  soloDuplicados.value = !soloDuplicados.value;
  if (soloDuplicados.value && grupos.value.length === 0) {
    void reloadDuplicados();
  }
}

function refrescar(): void {
  if (soloDuplicados.value) {
    void reloadDuplicados();
  } else {
    void reloadFromZero();
  }
}

function abrirFusion(grupo: GrupoCamarasDuplicadas, miembro: CamaraViewerItem): void {
  modalCamaraId.value = miembro.id;
  modalCamaraNombre.value = miembro.nombre;
  const otro = grupo.miembros.find((m) => m.id !== miembro.id);
  modalSugerencia.value = otro?.nombre ?? '';
  modalOpen.value = true;
}

function abrirFusionGrupo(grupo: GrupoCamarasDuplicadas): void {
  modalGrupoSeleccionado.value = grupo;
  modalGrupoOpen.value = true;
}

function abrirFusionMasiva(): void {
  errorMasiva.value = '';
  resultadoMasiva.value = null;
  modalMasivaOpen.value = true;
}

async function confirmarFusionMasiva(): Promise<void> {
  confirmandoMasiva.value = true;
  errorMasiva.value = '';
  resultadoMasiva.value = null;
  try {
    const respuesta = await mergeMasivoCamaras();
    resultadoMasiva.value =
      `${respuesta.grupos_fusionados} de ${respuesta.total_grupos} grupos fusionados` +
      (respuesta.grupos_con_error > 0 ? ` — ${respuesta.grupos_con_error} con error.` : '.');
    await Promise.all([reloadDuplicados(), reloadFromZero()]);
  } catch (err: unknown) {
    errorMasiva.value = err instanceof Error ? err.message : 'No se pudo ejecutar la fusión masiva.';
  } finally {
    confirmandoMasiva.value = false;
  }
}

async function handleMerged(): Promise<void> {
  modalOpen.value = false;
  await Promise.all([reloadDuplicados(), reloadFromZero()]);
}

function handleModalError(message: string): void {
  error.value = message;
}

onMounted(async () => {
  await reloadFromZero();

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && !soloDuplicados.value) void loadNextPage();
      }
    },
    { root: scrollEl.value, rootMargin: '300px 0px', threshold: 0.1 },
  );
  if (sentinel.value) observer.observe(sentinel.value);
});

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
  if (observer) observer.disconnect();
});
</script>

<style scoped>
.camaras-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.camaras-viewer__toolbar {
  padding: 4px 0 14px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.camaras-viewer__toolbar-row {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}

.camaras-viewer__search {
  position: relative;
  flex: 1;
  min-width: 200px;
}

.camaras-viewer__search i {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-neutral-500);
  font-size: 15px;
  pointer-events: none;
}

.camaras-viewer__search input {
  width: 100%;
  min-height: 38px;
  padding: 6px 10px 6px 33px;
  font-size: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.camaras-viewer__view-toggle {
  display: inline-flex;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.camaras-viewer__view-option {
  display: inline-flex;
  align-items: center;
  padding: 7px 12px;
  font-size: 15px;
  color: var(--color-neutral-400);
  background: transparent;
  border: 0;
  border-left: 1px solid var(--color-divider);
  cursor: pointer;
}

.camaras-viewer__view-option:first-child { border-left: 0; }

.camaras-viewer__view-option.is-active {
  color: var(--color-accent);
  box-shadow: inset 0 0 0 1px var(--color-accent);
}

.camaras-viewer__chips-row { flex-wrap: wrap; gap: 7px; }

.camaras-viewer__chips-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-neutral-500);
  margin-right: 2px;
}

.camaras-viewer__chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  font-size: 11.5px;
  cursor: pointer;
  border: 1px solid var(--color-divider);
  background: transparent;
  color: color-mix(in srgb, var(--color-text) 66%, transparent);
}

.camaras-viewer__chip:hover { border-color: var(--color-accent); }

.camaras-viewer__chip.is-active {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}

.camaras-viewer__chip--duplicadas.is-active {
  border-color: var(--color-state-warn);
  background: color-mix(in srgb, var(--color-state-warn) 16%, transparent);
  color: var(--color-state-warn);
}

.camaras-viewer__chip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.camaras-viewer__chip-dot.is-ok { background: var(--color-state-ok); }
.camaras-viewer__chip-dot.is-warn { background: var(--color-state-warn); }
.camaras-viewer__chip-dot.is-error { background: var(--color-state-error); }
.camaras-viewer__chip-dot.is-idle { background: var(--color-state-idle); }

.camaras-viewer__count {
  margin-left: auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
  white-space: nowrap;
}

.camaras-viewer__count strong { color: var(--color-text); font-weight: 500; }

.camaras-viewer__inline-error {
  margin-bottom: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
  font-size: 12.5px;
}

.camaras-viewer__scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.camaras-viewer__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 11px;
}

@media (max-width: 1280px) { .camaras-viewer__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1024px) { .camaras-viewer__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .camaras-viewer__grid { grid-template-columns: 1fr; } }

.camaras-viewer__list-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 14px;
  align-items: start;
}

@media (max-width: 1100px) { .camaras-viewer__list-layout { grid-template-columns: 1fr; } }

.camaras-viewer__list {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.camaras-viewer__list-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 11px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.15s ease;
}

.camaras-viewer__list-row:hover { background: color-mix(in srgb, var(--color-text) 5%, transparent); }

.camaras-viewer__list-row.is-selected {
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
}

.camaras-viewer__list-dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.camaras-viewer__list-dot.is-ok { background: var(--color-state-ok); }
.camaras-viewer__list-dot.is-warn { background: var(--color-state-warn); }
.camaras-viewer__list-dot.is-error { background: var(--color-state-error); }
.camaras-viewer__list-dot.is-idle { background: var(--color-state-idle); }

.camaras-viewer__list-nombre {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.camaras-viewer__list-stat {
  flex: none;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 48%, transparent);
}

.camaras-viewer__list-estado {
  flex: none;
  width: 96px;
  text-align: right;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.camaras-viewer__preview {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.camaras-viewer__preview-kicker {
  display: block;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.camaras-viewer__preview-title { margin: 5px 0 0; font-size: 18px; }

.camaras-viewer__preview-tags { display: flex; gap: 6px; flex-wrap: wrap; }

.camaras-viewer__preview-tag {
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  border: 1px solid var(--color-divider);
  color: color-mix(in srgb, var(--color-text) 65%, transparent);
}

.camaras-viewer__preview-tag.is-accent {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.camaras-viewer__preview-stats {
  display: flex;
  gap: 18px;
}

.camaras-viewer__preview-stat { display: flex; flex-direction: column; gap: 2px; }

.camaras-viewer__preview-label {
  font-size: 10.5px;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.camaras-viewer__preview-stat strong {
  font-family: var(--font-heading);
  font-size: 17px;
  font-variant-numeric: tabular-nums;
}

.camaras-viewer__state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  max-width: 260px;
  margin: 34px auto;
  padding: 34px 22px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
  text-align: center;
}

.camaras-viewer__state-box i { font-size: 26px; color: var(--color-neutral-600); margin-bottom: 4px; }
.camaras-viewer__state-box h3 { font-size: 15px; font-weight: 500; margin: 0; }
.camaras-viewer__state-box p {
  font-size: 12.5px;
  line-height: 1.5;
  margin: 0;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.camaras-viewer__state-box.is-error { box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-error) 45%, transparent); }
.camaras-viewer__state-box.is-error i { color: var(--color-state-error); }

.camaras-viewer__loading-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.camaras-viewer__spin { font-size: 14px; animation: spin 1s linear infinite; }
.camaras-viewer__sentinel { height: 2px; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.camaras-viewer__grupos {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.camaras-viewer__grupo-card {
  padding: 14px;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.camaras-viewer__grupo-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.camaras-viewer__grupo-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-state-warn) 16%, transparent);
  color: var(--color-state-warn);
  font-size: 11px;
}

.camaras-viewer__grupo-fusionar-todas {
  margin-left: auto;
  padding: 4px 10px;
  font-size: 11.5px;
}

.camaras-viewer__grupo-miembros {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 11px;
}
</style>
