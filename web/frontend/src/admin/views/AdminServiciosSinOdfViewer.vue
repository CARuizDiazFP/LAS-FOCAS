<!--
  Nombre de archivo: AdminServiciosSinOdfViewer.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminServiciosSinOdfViewer.vue
  Descripción: Dashboard /admin/servicios/viewer/ServiciosSinOdf — listado con scroll infinito de Servicios Activos sin ODF resuelta, chips de categoría con conteo real y modal de asociación manual
-->
<template>
  <section class="servicios-sin-odf-viewer">
    <AdminPageHeader
      kicker="Panel admin · Viewer"
      title="Servicios sin ODF"
      subtitle="Servicios Activos verificables sin ODF Cromo resuelta, con causa probable y sugerencia de ODF cuando el dato alcanza."
    />

    <div class="servicios-sin-odf-viewer__toolbar">
      <div class="servicios-sin-odf-viewer__toolbar-row">
        <div class="servicios-sin-odf-viewer__search">
          <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
          <input v-model="query" type="search" placeholder="Buscar por Nº de servicio o cliente" @input="onSearchInput" />
        </div>

        <button class="btn primary" type="button" :disabled="loading" @click="refrescar">
          <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
          Actualizar
        </button>
      </div>

      <div class="servicios-sin-odf-viewer__toolbar-row servicios-sin-odf-viewer__chips-row">
        <span class="servicios-sin-odf-viewer__chips-label">Categoría</span>
        <button
          type="button"
          :class="['servicios-sin-odf-viewer__chip', { 'is-active': filtroCategoria === '' }]"
          @click="setCategoria('')"
        >
          Todas
        </button>
        <button
          v-for="categoria in categorias"
          :key="categoria"
          type="button"
          :class="['servicios-sin-odf-viewer__chip', { 'is-active': filtroCategoria === categoria }]"
          @click="setCategoria(categoria)"
        >
          <span
            :class="['servicios-sin-odf-viewer__chip-dot', `is-${categoriaServicioToken(categoria)}`]"
            aria-hidden="true"
          ></span>
          {{ categoriaServicioLabel(categoria) }}
          <span class="servicios-sin-odf-viewer__chip-count">{{ conteos[categoria] ?? (cargandoConteos ? '…' : '—') }}</span>
        </button>

        <span class="servicios-sin-odf-viewer__count">
          <strong>{{ total.toLocaleString('es-AR') }}</strong> servicios sin ODF · mostrando {{ items.length }}
        </span>
      </div>
    </div>

    <div v-if="error" class="servicios-sin-odf-viewer__inline-error">{{ error }}</div>

    <div ref="scrollEl" class="servicios-sin-odf-viewer__scroll">
      <template v-if="items.length > 0">
        <div class="servicios-sin-odf-viewer__grid">
          <ServicioSinOdfCard v-for="item in items" :key="item.id" :servicio="item" @asociar="abrirModal" />
        </div>
      </template>

      <div v-else-if="!loading" class="servicios-sin-odf-viewer__state-box">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <h3>Ningún servicio coincide</h3>
        <p>Probá con otro texto o quitá el filtro de categoría.</p>
      </div>

      <div v-if="loading && items.length > 0" class="servicios-sin-odf-viewer__loading-more">
        <i class="ph ph-circle-notch servicios-sin-odf-viewer__spin" aria-hidden="true"></i>
        Cargando más servicios...
      </div>

      <div v-if="loading && items.length === 0" class="servicios-sin-odf-viewer__state-box">
        <i class="ph ph-circle-notch servicios-sin-odf-viewer__spin" aria-hidden="true"></i>
        <h3>Cargando servicios...</h3>
      </div>

      <div ref="sentinel" class="servicios-sin-odf-viewer__sentinel" aria-hidden="true"></div>
    </div>

    <ModalAsociarOdf
      :open="modalOpen"
      :servicio-id="modalServicioId"
      :servicio-numero="modalServicioNumero"
      @close="modalOpen = false"
      @asociado="handleAsociado"
      @error="handleModalError"
    />
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';

import AdminPageHeader from '../components/AdminPageHeader.vue';
import ModalAsociarOdf from '../../components/infra/ModalAsociarOdf.vue';
import ServicioSinOdfCard from '../../components/infra/ServicioSinOdfCard.vue';
import {
  CATEGORIAS_SERVICIO_SIN_ODF,
  categoriaServicioLabel,
  categoriaServicioToken,
  listarServiciosSinOdf,
  type ServicioSinOdfItem,
} from '../../api/serviciosOdf';

const LIMIT = 60;

const categorias = CATEGORIAS_SERVICIO_SIN_ODF;

const query = ref('');
const items = ref<ServicioSinOdfItem[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref('');
const offset = ref(0);
const hasMore = ref(true);
const sentinel = ref<HTMLElement | null>(null);
const scrollEl = ref<HTMLElement | null>(null);
const filtroCategoria = ref('');

const conteos = ref<Partial<Record<string, number>>>({});
const cargandoConteos = ref(false);

const modalOpen = ref(false);
const modalServicioId = ref<number | null>(null);
const modalServicioNumero = ref('');

let observer: IntersectionObserver | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function mergeItems(next: ServicioSinOdfItem[]): void {
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
    const response = await listarServiciosSinOdf({
      q: query.value.trim(),
      categoria: filtroCategoria.value || undefined,
      limit: LIMIT,
      offset: offset.value,
    });
    total.value = response.total;
    mergeItems(response.items);
    offset.value += response.items.length;
    hasMore.value = response.items.length === LIMIT && offset.value < response.total;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo consultar los Servicios sin ODF';
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

/** Un conteo por categoría vía `limit: 0` (el modo barato documentado por
 * `listar_servicios_sin_odf` para "sólo quiero el total"), respetando el mismo `q` que el
 * listado — nunca se inventa un conteo, se pide el real. Si una categoría falla, no rompe el
 * resto: simplemente esa chip queda sin número. */
async function reloadConteos(): Promise<void> {
  cargandoConteos.value = true;
  try {
    const entradas = await Promise.all(
      categorias.map(async (categoria) => {
        try {
          const respuesta = await listarServiciosSinOdf({ categoria, q: query.value.trim(), limit: 0 });
          return [categoria, respuesta.total] as const;
        } catch {
          return [categoria, null] as const;
        }
      }),
    );
    const next: Partial<Record<string, number>> = {};
    for (const [categoria, valor] of entradas) {
      if (valor != null) next[categoria] = valor;
    }
    conteos.value = next;
  } finally {
    cargandoConteos.value = false;
  }
}

function onSearchInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    void reloadFromZero();
    void reloadConteos();
  }, 320);
}

function setCategoria(value: string): void {
  filtroCategoria.value = filtroCategoria.value === value ? '' : value;
  void reloadFromZero();
}

function refrescar(): void {
  void reloadFromZero();
  void reloadConteos();
}

function abrirModal(servicio: ServicioSinOdfItem): void {
  modalServicioId.value = servicio.id;
  modalServicioNumero.value = servicio.servicio_id;
  modalOpen.value = true;
}

async function handleAsociado(): Promise<void> {
  modalOpen.value = false;
  // El Servicio recién asociado deja de aparecer en el listado (tiene override) — recargar
  // desde cero para no mostrar una fila resuelta como si siguiera pendiente.
  await Promise.all([reloadFromZero(), reloadConteos()]);
}

function handleModalError(message: string): void {
  error.value = message;
}

onMounted(async () => {
  await Promise.all([reloadFromZero(), reloadConteos()]);

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) void loadNextPage();
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
.servicios-sin-odf-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.servicios-sin-odf-viewer__toolbar {
  padding: 4px 0 14px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.servicios-sin-odf-viewer__toolbar-row {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}

.servicios-sin-odf-viewer__search {
  position: relative;
  flex: 1;
  min-width: 220px;
}

.servicios-sin-odf-viewer__search i {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-neutral-500);
  font-size: 15px;
  pointer-events: none;
}

.servicios-sin-odf-viewer__search input {
  width: 100%;
  min-height: 38px;
  padding: 6px 10px 6px 33px;
  font-size: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.servicios-sin-odf-viewer__chips-row { flex-wrap: wrap; gap: 7px; }

.servicios-sin-odf-viewer__chips-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-neutral-500);
  margin-right: 2px;
}

.servicios-sin-odf-viewer__chip {
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

.servicios-sin-odf-viewer__chip:hover { border-color: var(--color-accent); }

.servicios-sin-odf-viewer__chip.is-active {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}

.servicios-sin-odf-viewer__chip-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.servicios-sin-odf-viewer__chip-dot.is-ok { background: var(--color-state-ok); }
.servicios-sin-odf-viewer__chip-dot.is-warn { background: var(--color-state-warn); }
.servicios-sin-odf-viewer__chip-dot.is-error { background: var(--color-state-error); }
.servicios-sin-odf-viewer__chip-dot.is-idle { background: var(--color-state-idle); }

.servicios-sin-odf-viewer__chip-count {
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.servicios-sin-odf-viewer__count {
  margin-left: auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
  white-space: nowrap;
}

.servicios-sin-odf-viewer__count strong { color: var(--color-text); font-weight: 500; }

.servicios-sin-odf-viewer__inline-error {
  margin-bottom: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
  font-size: 12.5px;
}

.servicios-sin-odf-viewer__scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.servicios-sin-odf-viewer__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 11px;
}

@media (max-width: 1280px) { .servicios-sin-odf-viewer__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1024px) { .servicios-sin-odf-viewer__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .servicios-sin-odf-viewer__grid { grid-template-columns: 1fr; } }

.servicios-sin-odf-viewer__state-box {
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

.servicios-sin-odf-viewer__state-box i { font-size: 26px; color: var(--color-neutral-600); margin-bottom: 4px; }
.servicios-sin-odf-viewer__state-box h3 { font-size: 15px; font-weight: 500; margin: 0; }
.servicios-sin-odf-viewer__state-box p {
  font-size: 12.5px;
  line-height: 1.5;
  margin: 0;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.servicios-sin-odf-viewer__loading-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.servicios-sin-odf-viewer__spin { font-size: 14px; animation: spin 1s linear infinite; }
.servicios-sin-odf-viewer__sentinel { height: 2px; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
