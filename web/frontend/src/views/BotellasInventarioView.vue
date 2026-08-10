<!--
  Nombre de archivo: BotellasInventarioView.vue
  Ubicación de archivo: web/frontend/src/views/BotellasInventarioView.vue
  Descripción: Listado unificado de Botellas (Cromo + legado Infra/Baneos) — búsqueda con scroll infinito y toggle grilla/lista
-->
<template>
  <section class="botellas-view">
    <header class="botellas-view__header">
      <span class="botellas-view__kicker">Infraestructura FO</span>
      <div class="botellas-view__heading-row">
        <h1>Botellas</h1>
        <p class="botellas-view__subtitle">
          Cromo (siempre primero) + legado Infra/Baneos, con paginación incremental.
        </p>
      </div>
    </header>

    <hr class="noc-rule botellas-view__rule" />

    <div class="botellas-view__toolbar">
      <div class="botellas-view__toolbar-row">
        <div class="botellas-view__search">
          <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
          <input
            v-model="query"
            type="search"
            placeholder="Buscar por nombre, calle o localidad"
            @input="onSearchInput"
          />
        </div>

        <div class="botellas-view__view-toggle" role="radiogroup" aria-label="Tipo de vista">
          <button
            type="button"
            role="radio"
            :aria-checked="vista === 'grid'"
            :class="['botellas-view__view-option', { 'is-active': vista === 'grid' }]"
            title="Vista grilla"
            @click="setVista('grid')"
          >
            <i class="ph ph-squares-four" aria-hidden="true"></i>
          </button>
          <button
            type="button"
            role="radio"
            :aria-checked="vista === 'list'"
            :class="['botellas-view__view-option', { 'is-active': vista === 'list' }]"
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

      <div class="botellas-view__toolbar-row">
        <span class="botellas-view__count">
          <strong>{{ total.toLocaleString('es-AR') }}</strong> botellas · mostrando {{ items.length }}
        </span>
      </div>
    </div>

    <div ref="scrollEl" class="botellas-view__scroll">
      <template v-if="items.length > 0">
        <div v-if="vista === 'grid'" class="botellas-view__grid">
          <BotellaCard
            v-for="item in items"
            :key="itemKey(item)"
            :botella="item"
            @open-detail="openBotellaDetail"
          />
        </div>

        <div v-else class="botellas-view__list">
          <div
            v-for="item in items"
            :key="itemKey(item)"
            role="button"
            tabindex="0"
            class="botellas-view__list-row"
            @click="openBotellaDetail(item)"
            @keyup.enter="openBotellaDetail(item)"
          >
            <span :class="['botellas-view__list-origen', `is-${item.origen}`]">{{ item.origen === 'cromo' ? 'Cromo' : 'Legado' }}</span>
            <span
              v-if="item.origen === 'legado'"
              :class="['botellas-view__list-dot', `is-${estadoBotellaToken(item.estado)}`]"
              aria-hidden="true"
            ></span>
            <span class="botellas-view__list-nombre">{{ item.nombre || `Botella ${item.id}` }}</span>
            <span class="botellas-view__list-id">ID {{ item.id }}</span>
            <span class="botellas-view__list-estado">{{ item.origen === 'legado' ? (item.estado || 'LIBRE') : '—' }}</span>
          </div>
        </div>
      </template>

      <div v-else-if="!loading && !error" class="botellas-view__state-box">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <h3>Ninguna botella coincide</h3>
        <p>Probá con el nombre, la calle o la localidad, o quitá el filtro.</p>
        <button class="btn subtle" type="button" @click="clearFiltros">Limpiar búsqueda</button>
      </div>

      <div v-else-if="error && items.length === 0" class="botellas-view__state-box is-error">
        <i class="ph ph-warning-circle" aria-hidden="true"></i>
        <h3>No se pudo consultar botellas</h3>
        <p>{{ error }}</p>
        <button class="btn primary" type="button" @click="reloadFromZero">
          <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
          Reintentar
        </button>
      </div>

      <div v-if="loading && items.length > 0" class="botellas-view__loading-more">
        <i class="ph ph-circle-notch botellas-view__spin" aria-hidden="true"></i>
        Cargando más botellas...
      </div>

      <div ref="sentinel" class="botellas-view__sentinel" aria-hidden="true"></div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { estadoBotellaToken, searchBotellas, type BotellaUnificadaItem } from '../api/botellas';
import BotellaCard from '../components/infra/BotellaCard.vue';

const LIMIT = 30;
const VISTA_STORAGE_KEY = 'botellas.vista';
const router = useRouter();

const query = ref('');
const items = ref<BotellaUnificadaItem[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref('');
const offset = ref(0);
const hasMore = ref(true);
const sentinel = ref<HTMLElement | null>(null);
const scrollEl = ref<HTMLElement | null>(null);

const vista = ref<'grid' | 'list'>(
  (localStorage.getItem(VISTA_STORAGE_KEY) as 'grid' | 'list' | null) === 'list' ? 'list' : 'grid',
);

let observer: IntersectionObserver | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

// Un n_id de Cromo y un Camara.id legado son espacios de ID independientes que pueden coincidir en
// valor sin ser la misma fila — la key SIEMPRE es el compuesto origen+id, nunca el id solo.
function itemKey(item: BotellaUnificadaItem): string {
  return `${item.origen}:${item.id}`;
}

function mergeItems(next: BotellaUnificadaItem[]): void {
  const seen = new Set(items.value.map(itemKey));
  for (const item of next) {
    const key = itemKey(item);
    if (seen.has(key)) continue;
    seen.add(key);
    items.value.push(item);
  }
}

async function loadNextPage(): Promise<void> {
  if (loading.value || !hasMore.value) return;

  loading.value = true;
  error.value = '';
  try {
    const response = await searchBotellas({ q: query.value.trim(), limit: LIMIT, offset: offset.value });

    total.value = response.total;
    mergeItems(response.botellas);
    offset.value += response.botellas.length;
    hasMore.value = response.botellas.length === LIMIT && offset.value < response.total;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo consultar botellas';
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

function clearFiltros(): void {
  query.value = '';
  void reloadFromZero();
}

function setVista(next: 'grid' | 'list'): void {
  vista.value = next;
  localStorage.setItem(VISTA_STORAGE_KEY, next);
}

function openBotellaDetail(item: BotellaUnificadaItem): void {
  void router.push({ path: `/infra/Camaras/Botellas/ID${item.id}`, query: { origen: item.origen } });
}

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
.botellas-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.botellas-view__header {
  padding: 22px 26px 0;
}

.botellas-view__kicker {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.botellas-view__heading-row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
}

.botellas-view__heading-row h1 {
  font-size: 27px;
  margin: 3px 0 0;
}

.botellas-view__subtitle {
  margin: 0 0 4px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 52%, transparent);
}

.botellas-view__rule {
  margin: 14px 0 0;
}

.botellas-view__toolbar {
  padding: 15px 26px 14px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.botellas-view__toolbar-row {
  display: flex;
  align-items: center;
  gap: 9px;
}

.botellas-view__search {
  position: relative;
  flex: 1;
}

.botellas-view__search i {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-neutral-500);
  font-size: 15px;
  pointer-events: none;
}

.botellas-view__search input {
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

.botellas-view__search input:hover {
  border-color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.botellas-view__search input:focus-visible {
  border-color: var(--color-accent);
  outline-offset: 0;
}

.botellas-view__view-toggle {
  display: inline-flex;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.botellas-view__view-option {
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

.botellas-view__view-option:first-child {
  border-left: 0;
}

.botellas-view__view-option.is-active {
  color: var(--color-accent);
  box-shadow: inset 0 0 0 1px var(--color-accent);
}

.botellas-view__count {
  margin-left: auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
  white-space: nowrap;
}

.botellas-view__count strong {
  color: var(--color-text);
  font-weight: 500;
}

.botellas-view__scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 12px 26px 30px;
}

.botellas-view__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 11px;
}

@media (max-width: 1280px) {
  .botellas-view__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1024px) {
  .botellas-view__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .botellas-view__grid { grid-template-columns: 1fr; }
}

.botellas-view__list {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.botellas-view__list-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 11px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.15s ease;
}

.botellas-view__list-row:hover {
  background: color-mix(in srgb, var(--color-text) 5%, transparent);
}

.botellas-view__list-origen {
  flex: none;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  letter-spacing: 0.06em;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.botellas-view__list-origen.is-cromo {
  background: color-mix(in srgb, var(--color-accent) 18%, transparent);
  color: var(--color-accent-200);
}

.botellas-view__list-dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}
.botellas-view__list-dot.is-ok { background: var(--color-state-ok); }
.botellas-view__list-dot.is-warn { background: var(--color-state-warn); }
.botellas-view__list-dot.is-error { background: var(--color-state-error); }

.botellas-view__list-nombre {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.botellas-view__list-id {
  flex: none;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 48%, transparent);
}

.botellas-view__list-estado {
  flex: none;
  width: 88px;
  text-align: right;
  font-family: var(--font-heading);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: var(--color-accent);
}

.botellas-view__state-box {
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

.botellas-view__state-box i {
  font-size: 26px;
  color: var(--color-neutral-600);
  margin-bottom: 4px;
}

.botellas-view__state-box h3 {
  font-size: 15px;
  font-weight: 500;
  margin: 0;
}

.botellas-view__state-box p {
  font-size: 12.5px;
  line-height: 1.5;
  margin: 0;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.botellas-view__state-box.is-error {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-error) 45%, transparent);
}

.botellas-view__state-box.is-error i {
  color: var(--color-state-error);
}

.botellas-view__loading-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.botellas-view__spin {
  font-size: 14px;
  animation: spin 1s linear infinite;
}

.botellas-view__sentinel {
  height: 2px;
}

@media (max-width: 700px) {
  .botellas-view__toolbar-row {
    flex-wrap: wrap;
  }
}
</style>
