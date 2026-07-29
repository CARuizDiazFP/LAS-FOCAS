<!--
  Nombre de archivo: ServiciosView.vue
  Ubicación de archivo: web/frontend/src/views/ServiciosView.vue
  Descripción: Visor de servicios — búsqueda multipropósito, chips de filtro, grilla/lista con scroll infinito
-->
<template>
  <section class="servicios-view">
    <header class="servicios-view__header">
      <span class="servicios-view__kicker">Operación diaria</span>
      <div class="servicios-view__heading-row">
        <h1>Servicios</h1>
        <p class="servicios-view__subtitle">Buscador multipropósito con paginación incremental.</p>
      </div>
    </header>

    <hr class="noc-rule servicios-view__rule" />

    <div class="servicios-view__toolbar">
      <div class="servicios-view__toolbar-row">
        <div class="servicios-view__search">
          <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
          <input
            v-model="query"
            type="search"
            placeholder="Buscar por ID, cliente, domicilio, tipo o estado"
            @input="onSearchInput"
          />
        </div>

        <div class="servicios-view__view-toggle" role="radiogroup" aria-label="Tipo de vista">
          <button
            type="button"
            role="radio"
            :aria-checked="vista === 'grid'"
            :class="['servicios-view__view-option', { 'is-active': vista === 'grid' }]"
            title="Vista grilla"
            @click="setVista('grid')"
          >
            <i class="ph ph-squares-four" aria-hidden="true"></i>
          </button>
          <button
            type="button"
            role="radio"
            :aria-checked="vista === 'list'"
            :class="['servicios-view__view-option', { 'is-active': vista === 'list' }]"
            title="Vista lista"
            @click="setVista('list')"
          >
            <i class="ph ph-rows" aria-hidden="true"></i>
          </button>
        </div>

        <button class="btn primary" type="button" :disabled="loading" @click="reloadFromZero">
          <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
          {{ loading && items.length === 0 ? 'Buscando...' : 'Actualizar' }}
        </button>
      </div>

      <div class="servicios-view__toolbar-row servicios-view__chips-row">
        <span class="servicios-view__chips-label">Filtros</span>

        <button
          v-for="chip in tipoChips"
          :key="chip.value"
          type="button"
          :class="['servicios-view__chip', { 'is-active': filtros.tipo === chip.value }]"
          @click="setTipo(chip.value)"
        >
          {{ chip.label }}
        </button>

        <button
          v-for="chip in estadoChips"
          :key="chip.value"
          type="button"
          :class="['servicios-view__chip', { 'is-active': filtros.estado === chip.value }]"
          @click="setEstado(chip.value)"
        >
          <span :class="['servicios-view__chip-dot', `is-${chip.token}`]" aria-hidden="true"></span>
          {{ chip.label }}
        </button>

        <span class="servicios-view__count">
          <strong>{{ total.toLocaleString('es-AR') }}</strong> servicios · mostrando {{ items.length }}
        </span>
      </div>
    </div>

    <div ref="scrollEl" class="servicios-view__scroll">
      <template v-if="items.length > 0">
        <div v-if="vista === 'grid'" class="servicios-view__grid">
          <ServicioCard
            v-for="item in items"
            :key="item.numero_primer_servicio"
            :servicio="item"
            @open-detail="openServicioDetail"
          />
        </div>

        <div v-else class="servicios-view__list-layout">
          <div class="servicios-view__list">
            <div
              v-for="item in items"
              :key="item.numero_primer_servicio"
              role="button"
              tabindex="0"
              :class="['servicios-view__list-row', { 'is-selected': item.numero_primer_servicio === selectedIdOrigen }]"
              @click="selectedIdOrigen = item.numero_primer_servicio"
              @keyup.enter="selectedIdOrigen = item.numero_primer_servicio"
            >
              <span :class="['servicios-view__list-dot', `is-${estadoServicioToken(item.estado_servicio)}`]" aria-hidden="true"></span>
              <span class="servicios-view__list-cliente">{{ item.nombre_cliente || 'Cliente sin dato' }}</span>
              <span class="servicios-view__list-historico">{{ historicoLabel(item) }}</span>
              <span class="servicios-view__list-tipo">{{ (item.tipo_servicio || 'SERVICIO').toUpperCase() }}</span>
              <span class="servicios-view__list-cta">{{ ctaLabel(item) }}</span>
            </div>
          </div>

          <aside v-if="selectedItem" class="servicios-view__preview">
            <div>
              <span class="servicios-view__preview-kicker">Vista previa</span>
              <h2 class="servicios-view__preview-title">{{ selectedItem.nombre_cliente || 'Cliente sin dato' }}</h2>
              <p class="servicios-view__preview-domicilio">{{ previewDomicilio(selectedItem) }}</p>
            </div>

            <div class="servicios-view__preview-tags">
              <span class="servicios-view__preview-tag is-accent">{{ selectedItem.estado_servicio || 'Sin estado' }}</span>
              <span class="servicios-view__preview-tag">{{ (selectedItem.tipo_servicio || 'SERVICIO').toUpperCase() }}</span>
              <span v-if="selectedItem.sla_prometido" class="servicios-view__preview-tag is-outline">SLA {{ selectedItem.sla_prometido }}</span>
            </div>

            <div class="servicios-view__hairline"></div>

            <div class="servicios-view__preview-historico">
              <span class="servicios-view__preview-label">Histórico de IDs</span>
              <div class="servicios-view__preview-nodos">
                <span class="servicios-view__preview-nodo">{{ selectedItem.numero_primer_servicio }}</span>
                <template v-if="selectedItem.numero_linea && selectedItem.numero_linea !== selectedItem.numero_primer_servicio">
                  <i class="ph ph-arrow-right" aria-hidden="true"></i>
                  <span class="servicios-view__preview-nodo is-current">{{ selectedItem.numero_linea }}</span>
                </template>
              </div>
            </div>

            <div class="servicios-view__preview-stats">
              <div class="servicios-view__preview-stat">
                <span class="servicios-view__preview-label">Reclamos 12m</span>
                <strong>{{ selectedItem.reclamos?.length ?? 0 }}</strong>
              </div>
              <div class="servicios-view__preview-stat">
                <span class="servicios-view__preview-label">SLA prometido</span>
                <strong>{{ selectedItem.sla_prometido || '—' }}</strong>
              </div>
            </div>

            <button class="btn primary" type="button" @click="openServicioDetail(selectedItem.numero_primer_servicio)">
              Abrir detalle completo
              <i class="ph ph-arrow-right" aria-hidden="true"></i>
            </button>
          </aside>
        </div>
      </template>

      <div v-else-if="!loading && !error" class="servicios-view__state-box">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <h3>Ningún servicio coincide</h3>
        <p>Probá con el ID de origen, el nombre del cliente o quitá algún filtro.</p>
        <button class="btn subtle" type="button" @click="clearFiltros">Limpiar filtros</button>
      </div>

      <div v-else-if="error && items.length === 0" class="servicios-view__state-box is-error">
        <i class="ph ph-warning-circle" aria-hidden="true"></i>
        <h3>No se pudo consultar servicios</h3>
        <p>{{ error }}</p>
        <button class="btn primary" type="button" @click="reloadFromZero">
          <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
          Reintentar
        </button>
      </div>

      <div v-if="loading && items.length > 0" class="servicios-view__loading-more">
        <i class="ph ph-circle-notch servicios-view__spin" aria-hidden="true"></i>
        Cargando más servicios...
      </div>

      <div ref="sentinel" class="servicios-view__sentinel" aria-hidden="true"></div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { estadoServicioToken, searchServicios, type ServicioItem } from '../api/servicios';
import ServicioCard from '../components/servicios/ServicioCard.vue';

const LIMIT = 30;
const VISTA_STORAGE_KEY = 'servicios.vista';
const router = useRouter();

const query = ref('');
const items = ref<ServicioItem[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref('');
const offset = ref(0);
const hasMore = ref(true);
const sentinel = ref<HTMLElement | null>(null);
const scrollEl = ref<HTMLElement | null>(null);
const filtros = ref({ tipo: '', estado: '' });
const selectedIdOrigen = ref('');

const vista = ref<'grid' | 'list'>(
  (localStorage.getItem(VISTA_STORAGE_KEY) as 'grid' | 'list' | null) === 'list' ? 'list' : 'grid',
);

const tipoChips = [
  { label: 'Tipo: todos', value: '' },
  { label: 'TLS', value: 'TLS' },
  { label: 'VID', value: 'VID' },
];

const estadoChips = [
  { label: 'Activo', value: 'activo', token: 'ok' as const },
  { label: 'Observado', value: 'observado', token: 'warn' as const },
  { label: 'Baja', value: 'baja', token: 'error' as const },
];

const selectedItem = computed(() => {
  return items.value.find((item) => item.numero_primer_servicio === selectedIdOrigen.value) ?? items.value[0] ?? null;
});

let observer: IntersectionObserver | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function mergeItems(next: ServicioItem[]): void {
  const seen = new Set(items.value.map((item) => item.numero_primer_servicio));
  for (const item of next) {
    if (seen.has(item.numero_primer_servicio)) continue;
    seen.add(item.numero_primer_servicio);
    items.value.push(item);
  }
}

async function loadNextPage(): Promise<void> {
  if (loading.value || !hasMore.value) return;

  loading.value = true;
  error.value = '';
  try {
    const response = await searchServicios({
      q: query.value.trim(),
      tipo: filtros.value.tipo,
      estado: filtros.value.estado,
      limit: LIMIT,
      offset: offset.value,
    });

    total.value = response.total;
    mergeItems(response.servicios);
    offset.value += response.servicios.length;
    hasMore.value = response.servicios.length === LIMIT && offset.value < response.total;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo consultar servicios';
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

function onSearchInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    void reloadFromZero();
  }, 320);
}

function setTipo(value: string): void {
  if (filtros.value.tipo === value) return;
  filtros.value.tipo = value;
  void reloadFromZero();
}

function setEstado(value: string): void {
  filtros.value.estado = filtros.value.estado === value ? '' : value;
  void reloadFromZero();
}

function clearFiltros(): void {
  query.value = '';
  filtros.value = { tipo: '', estado: '' };
  void reloadFromZero();
}

function setVista(next: 'grid' | 'list'): void {
  vista.value = next;
  localStorage.setItem(VISTA_STORAGE_KEY, next);
}

function historicoLabel(item: ServicioItem): string {
  const origen = (item.numero_primer_servicio ?? '').trim();
  const linea = (item.numero_linea ?? '').trim() || origen;
  return origen === linea ? `Hist. ${origen}` : `${origen} → ${linea}`;
}

function ctaLabel(item: ServicioItem): string {
  const tipo = (item.tipo_servicio ?? '').trim().toUpperCase() || 'SERVICIO';
  const linea = (item.numero_linea ?? '').trim() || (item.numero_primer_servicio ?? '').trim();
  return `${tipo} ${linea}`;
}

function previewDomicilio(item: ServicioItem): string {
  const parts = [item.direccion, item.direccion_2, item.localidad, item.provincia]
    .map((value) => (value ?? '').trim())
    .filter((value) => value.length > 0);
  return parts.length > 0 ? parts.join(' · ') : 'Sin dato';
}

function openServicioDetail(idOrigen: string): void {
  const id = idOrigen.trim();
  if (!id) return;
  void router.push(`/servicios/ID/${encodeURIComponent(id)}`);
}

watch(items, (next) => {
  if (!next.some((item) => item.numero_primer_servicio === selectedIdOrigen.value)) {
    selectedIdOrigen.value = next[0]?.numero_primer_servicio ?? '';
  }
});

onMounted(async () => {
  await reloadFromZero();

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          void loadNextPage();
        }
      }
    },
    {
      root: scrollEl.value,
      rootMargin: '300px 0px',
      threshold: 0.1,
    },
  );

  if (sentinel.value) observer.observe(sentinel.value);
});

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
  if (observer) observer.disconnect();
});
</script>

<style scoped>
.servicios-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.servicios-view__header {
  padding: 22px 26px 0;
}

.servicios-view__kicker {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.servicios-view__heading-row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
}

.servicios-view__heading-row h1 {
  font-size: 27px;
  margin: 3px 0 0;
}

.servicios-view__subtitle {
  margin: 0 0 4px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 52%, transparent);
}

.servicios-view__rule {
  margin: 14px 0 0;
}

.servicios-view__toolbar {
  padding: 15px 26px 14px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.servicios-view__toolbar-row {
  display: flex;
  align-items: center;
  gap: 9px;
}

.servicios-view__search {
  position: relative;
  flex: 1;
}

.servicios-view__search i {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-neutral-500);
  font-size: 15px;
  pointer-events: none;
}

.servicios-view__search input {
  width: 100%;
  min-height: 38px;
  padding: 6px 10px 6px 33px;
  font-size: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
  caret-color: var(--color-accent);
}

.servicios-view__search input:hover {
  border-color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.servicios-view__search input:focus-visible {
  border-color: var(--color-accent);
  outline-offset: 0;
}

.servicios-view__view-toggle {
  display: inline-flex;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.servicios-view__view-option {
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

.servicios-view__view-option:first-child {
  border-left: 0;
}

.servicios-view__view-option.is-active {
  color: var(--color-accent);
  box-shadow: inset 0 0 0 1px var(--color-accent);
}

.servicios-view__chips-row {
  flex-wrap: wrap;
  gap: 7px;
}

.servicios-view__chips-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-neutral-500);
  margin-right: 2px;
}

.servicios-view__chip {
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

.servicios-view__chip:hover {
  border-color: var(--color-accent);
}

.servicios-view__chip.is-active {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}

.servicios-view__chip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.servicios-view__chip-dot.is-ok { background: var(--color-state-ok); }
.servicios-view__chip-dot.is-warn { background: var(--color-state-warn); }
.servicios-view__chip-dot.is-error { background: var(--color-state-error); }

.servicios-view__count {
  margin-left: auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
  white-space: nowrap;
}

.servicios-view__count strong {
  color: var(--color-text);
  font-weight: 500;
}

.servicios-view__scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 26px 30px;
}

.servicios-view__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 11px;
}

@media (max-width: 1280px) {
  .servicios-view__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1024px) {
  .servicios-view__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .servicios-view__grid { grid-template-columns: 1fr; }
}

.servicios-view__list-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 14px;
  align-items: start;
}

.servicios-view__list {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.servicios-view__list-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 11px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.15s ease;
}

.servicios-view__list-row:hover {
  background: color-mix(in srgb, var(--color-text) 5%, transparent);
}

.servicios-view__list-row.is-selected {
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
}

.servicios-view__list-dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}
.servicios-view__list-dot.is-ok { background: var(--color-state-ok); }
.servicios-view__list-dot.is-warn { background: var(--color-state-warn); }
.servicios-view__list-dot.is-error { background: var(--color-state-error); }

.servicios-view__list-cliente {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.servicios-view__list-historico {
  flex: none;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 48%, transparent);
}

.servicios-view__list-tipo {
  flex: none;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  letter-spacing: 0.06em;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.servicios-view__list-cta {
  flex: none;
  width: 88px;
  text-align: right;
  font-family: var(--font-heading);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: var(--color-accent);
}

.servicios-view__preview {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.servicios-view__preview-kicker {
  display: block;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.servicios-view__preview-title {
  margin: 5px 0 0;
  font-size: 20px;
  line-height: 1.2;
  text-wrap: pretty;
}

.servicios-view__preview-domicilio {
  margin: 5px 0 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 52%, transparent);
}

.servicios-view__preview-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.servicios-view__preview-tag {
  padding: 3px 9px;
  border-radius: 6px;
  font-size: 10.5px;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.servicios-view__preview-tag.is-accent {
  background: color-mix(in srgb, var(--color-accent) 16%, transparent);
  color: var(--color-accent-200);
}

.servicios-view__preview-tag.is-outline {
  background: transparent;
  border: 1px solid var(--color-accent);
  color: var(--color-accent);
}

.servicios-view__hairline {
  height: 1px;
  background: var(--color-divider);
}

.servicios-view__preview-historico {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.servicios-view__preview-label {
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-neutral-500);
}

.servicios-view__preview-nodos {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.servicios-view__preview-nodo {
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  padding: 3px 9px;
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.servicios-view__preview-nodo.is-current {
  background: transparent;
  border: 1px solid var(--color-accent);
  color: var(--color-accent);
}

.servicios-view__preview-stats {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.servicios-view__preview-stat {
  padding: 9px 10px;
  border-radius: var(--radius-md);
  background: var(--color-bg);
}

.servicios-view__preview-stat strong {
  display: block;
  margin-top: 3px;
  font-family: var(--font-heading);
  font-size: 17px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.servicios-view__state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  max-width: 230px;
  margin: 34px auto;
  padding: 34px 22px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
  text-align: center;
}

.servicios-view__state-box i {
  font-size: 26px;
  color: var(--color-neutral-600);
  margin-bottom: 4px;
}

.servicios-view__state-box h3 {
  font-size: 15px;
  font-weight: 500;
  margin: 0;
}

.servicios-view__state-box p {
  font-size: 12.5px;
  line-height: 1.5;
  margin: 0;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.servicios-view__state-box.is-error {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-error) 45%, transparent);
}

.servicios-view__state-box.is-error i {
  color: var(--color-state-error);
}

.servicios-view__loading-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.servicios-view__spin {
  font-size: 14px;
  animation: spin 1s linear infinite;
}

.servicios-view__sentinel {
  height: 2px;
}

@media (max-width: 1100px) {
  .servicios-view__list-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 700px) {
  .servicios-view__toolbar-row {
    flex-wrap: wrap;
  }
}
</style>
