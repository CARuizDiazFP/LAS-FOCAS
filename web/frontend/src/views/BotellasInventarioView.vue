<!--
  Nombre de archivo: BotellasInventarioView.vue
  Ubicación de archivo: web/frontend/src/views/BotellasInventarioView.vue
  Descripción: Listado unificado de Botellas (Cromo + legado Infra/Baneos) — búsqueda con scroll infinito y toggle grilla/lista
-->
<template>
  <ViewerShell
    bloque="botellas-view"
    :loading="activa.loading.value"
    :error="activa.error.value"
    :error-inline="false"
    :vacio="activa.items.value.length === 0 && !activa.error.value"
    :hay-mas="activa.hasMore.value"
    :texto-vacio="soloHuerfanas ? 'Sin huérfanas' : 'Ninguna botella coincide'"
    :icono-vacio="soloHuerfanas ? 'ph-check-circle' : 'ph-magnifying-glass'"
    :texto-cargando="soloHuerfanas ? 'Cargando más huérfanas...' : 'Cargando más botellas...'"
    ancho-estado="230px"
    @cargar-mas="activa.cargarSiguiente"
  >
    <template #toolbar>
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
              @input="activa.recargarConDebounce"
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

          <button
            class="btn primary"
            type="button"
            :disabled="activa.loading.value"
            @click="activa.recargarDesdeCero"
          >
            <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
            {{ activa.loading.value && activa.items.value.length === 0 ? 'Buscando...' : 'Actualizar' }}
          </button>
        </div>

        <div class="botellas-view__toolbar-row">
          <label class="botellas-view__toggle">
            <input type="checkbox" v-model="incluirNoOperativas" @change="reloadFromZero" :disabled="soloHuerfanas" />
            Mostrar No operativas
          </label>

          <label class="botellas-view__toggle">
            <input type="checkbox" v-model="soloHuerfanas" @change="onToggleSoloHuerfanas" />
            Sólo huérfanas (sin Cámara asociada)
          </label>

          <span class="botellas-view__count">
            <strong>{{ activa.total.value.toLocaleString('es-AR') }}</strong>
            {{ soloHuerfanas ? 'huérfanas' : 'botellas' }} · mostrando {{ activa.items.value.length }}
          </span>
        </div>

        <div v-if="soloHuerfanas && seleccionadas.size > 0" class="botellas-view__bulk-bar">
          <span>{{ seleccionadas.size }} seleccionada{{ seleccionadas.size !== 1 ? 's' : '' }}</span>
          <button class="btn primary" type="button" @click="modalAsociarOpen = true">Asociar a Cámara</button>
          <button class="btn subtle" type="button" @click="limpiarSeleccion">Deseleccionar todo</button>
        </div>
      </div>
    </template>

    <template v-if="soloHuerfanas">
      <div v-if="huerfanas.length > 0" class="botellas-view__list">
        <label
          v-for="h in huerfanas"
          :key="h.n_id"
          class="botellas-view__list-row botellas-view__list-row--huerfana"
        >
          <input
            type="checkbox"
            :checked="seleccionadas.has(claveHuerfana(h))"
            @change="toggleSeleccion(claveHuerfana(h))"
          />
          <span class="botellas-view__list-nombre">{{ h.nombre || `Botella ${h.n_id}` }}</span>
          <span class="botellas-view__list-id">n_id {{ h.n_id }}</span>
          <span class="botellas-view__list-estado">{{ h.localidad || h.calle || '—' }}</span>
          <button
            class="btn subtle"
            type="button"
            style="padding:3px 9px;font-size:11.5px"
            @click.stop="abrirAsociarIndividual(h.n_id)"
          >Asociar</button>
        </label>
      </div>
      <div v-else class="botellas-view__state-box is-error">
        <i class="ph ph-warning-circle" aria-hidden="true"></i>
        <h3>No se pudo consultar huérfanas</h3>
        <p>{{ errorHuerfanas }}</p>
        <button class="btn primary" type="button" @click="reloadHuerfanasFromZero">
          <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
          Reintentar
        </button>
      </div>
    </template>

    <template v-else>
      <template v-if="items.length > 0">
        <div v-if="vista === 'grid'" class="botellas-view__grid">
          <BotellaCard
            v-for="item in items"
            :key="itemKey(item)"
            :botella="item"
            :selected="seleccionadas.has(itemKey(item))"
            @open-detail="openBotellaDetail"
            @toggle-select="toggleSeleccion(itemKey(item))"
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
            <input
              type="checkbox"
              class="botellas-view__list-checkbox"
              :checked="seleccionadas.has(itemKey(item))"
              @click.stop
              @change="toggleSeleccion(itemKey(item))"
            />
            <span :class="['botellas-view__list-origen', `is-${item.origen}`]">{{ item.origen === 'cromo' ? 'Cromo' : 'Legado' }}</span>
            <span
              v-if="item.estado"
              :class="['botellas-view__list-dot', `is-${estadoBotellaToken(item.estado)}`]"
              aria-hidden="true"
            ></span>
            <RouterLink
              class="botellas-view__list-nombre"
              :to="botellaDetailPath(item.origen, item.id)"
              @click.stop
            >{{ item.nombre || `Botella ${item.id}` }}</RouterLink>
            <span class="botellas-view__list-id">ID {{ item.id }}</span>
            <span class="botellas-view__list-estado">{{ item.estado || '—' }}</span>
          </div>
        </div>
      </template>

      <div v-else class="botellas-view__state-box is-error">
        <i class="ph ph-warning-circle" aria-hidden="true"></i>
        <h3>No se pudo consultar botellas</h3>
        <p>{{ error }}</p>
        <button class="btn primary" type="button" @click="reloadFromZero">
          <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
          Reintentar
        </button>
      </div>
    </template>

    <template #vacio>
      <p v-if="soloHuerfanas">Ninguna Botella Cromo sin Cámara asociada coincide con la búsqueda actual.</p>
      <template v-else>
        <p>Probá con el nombre, la calle o la localidad, o quitá el filtro.</p>
        <button class="btn subtle" type="button" @click="clearFiltros">Limpiar búsqueda</button>
      </template>
    </template>

    <template #extra>
      <ModalAsociarHuerfanas
        :open="modalAsociarOpen"
        :n-ids="nIdsParaAsociar"
        @close="modalAsociarOpen = false"
        @asociada="handleAsociada"
      />

      <BotellasBulkActionsPanel
        v-if="!soloHuerfanas && seleccionadas.size > 0"
        :count="seleccionadas.size"
        v-model="estadoMasivoSeleccionado"
        :applying="aplicandoEstadoMasivo"
        :error="errorEstadoMasivo"
        @apply="aplicarEstadoMasivo"
        @clear="limpiarSeleccion"
      />
    </template>
  </ViewerShell>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import {
  estadoBotellaToken,
  listarBotellasHuerfanas,
  searchBotellas,
  updateBotellasEstadoMasivo,
  type BotellaClave,
  type BotellaHuerfanaItem,
  type BotellaOrigen,
  type BotellaUnificadaItem,
  type EstadoBotellaValor,
} from '../api/botellas';
import BotellaCard from '../components/infra/BotellaCard.vue';
import BotellasBulkActionsPanel from '../components/infra/BotellasBulkActionsPanel.vue';
import ModalAsociarHuerfanas from '../components/infra/ModalAsociarHuerfanas.vue';
import ViewerShell from '../components/viewer/ViewerShell.vue';
import { usePaginatedSearch } from '../composables/usePaginatedSearch';
import { botellaDetailPath } from '../utils/botellaLinks';

const LIMIT = 30;
const VISTA_STORAGE_KEY = 'botellas.vista';
const router = useRouter();

const query = ref('');
const incluirNoOperativas = ref(false);

// --- Botellas Cromo huérfanas (Caso 1: sin camara_id, no matchearon el backfill automático) ---
const soloHuerfanas = ref(false);
const seleccionadas = ref<Set<string>>(new Set());
const modalAsociarOpen = ref(false);
const nIdsParaAsociar = ref<number[]>([]);

// --- Cambio de estado masivo (Cromo + legado, clave compuesta origen:id) ---
const estadoMasivoSeleccionado = ref<EstadoBotellaValor>('NO_OPERATIVA');
const aplicandoEstadoMasivo = ref(false);
const errorEstadoMasivo = ref('');

const vista = ref<'grid' | 'list'>(
  (localStorage.getItem(VISTA_STORAGE_KEY) as 'grid' | 'list' | null) === 'list' ? 'list' : 'grid',
);

// Un n_id de Cromo y un Camara.id legado son espacios de ID independientes que pueden coincidir en
// valor sin ser la misma fila — la key SIEMPRE es el compuesto origen+id, nunca el id solo. Se
// reusa como clave de selección masiva además de key de Vue (`seleccionadas` guarda este string).
function itemKey(item: BotellaUnificadaItem): string {
  return `${item.origen}:${item.id}`;
}

function claveHuerfana(h: BotellaHuerfanaItem): string {
  return `cromo:${h.n_id}`;
}

function parseClave(clave: string): BotellaClave {
  const [origen, idTexto] = clave.split(':');
  return { origen: origen as BotellaOrigen, id: Number(idTexto) };
}

function limpiarSeleccion(): void {
  seleccionadas.value = new Set();
}

// Dos listas paginadas independientes (inventario y huérfanas), cada una con su error: el shell y la
// toolbar muestran la del modo activo. Recargar cualquiera de las dos vacía la selección.
const busqueda = usePaginatedSearch({
  limit: LIMIT,
  cargarPagina: async (offset, limit) => {
    const response = await searchBotellas({
      q: query.value.trim(),
      limit,
      offset,
      incluirNoOperativas: incluirNoOperativas.value,
    });
    return { items: response.botellas, total: response.total };
  },
  claveItem: itemKey,
  alReiniciar: limpiarSeleccion,
  mensajeError: 'No se pudo consultar botellas',
});

const busquedaHuerfanas = usePaginatedSearch({
  limit: LIMIT,
  cargarPagina: async (offset, limit) => {
    const data = await listarBotellasHuerfanas(
      new URLSearchParams({ q: query.value.trim(), limit: String(limit), offset: String(offset) }),
    );
    return { items: data.botellas ?? [], total: data.total ?? 0 };
  },
  claveItem: (h: BotellaHuerfanaItem) => h.n_id,
  alReiniciar: limpiarSeleccion,
  mensajeError: 'No se pudo consultar huérfanas',
});

const { items, error, recargarDesdeCero: reloadFromZero } = busqueda;
const { items: huerfanas, error: errorHuerfanas, recargarDesdeCero: reloadHuerfanasFromZero } = busquedaHuerfanas;

// En el template se leen con `.value`: los refs anidados en un objeto no se desenvuelven solos.
const activa = computed(() => (soloHuerfanas.value ? busquedaHuerfanas : busqueda));

function clearFiltros(): void {
  query.value = '';
  void activa.value.recargarDesdeCero();
}

function setVista(next: 'grid' | 'list'): void {
  vista.value = next;
  localStorage.setItem(VISTA_STORAGE_KEY, next);
}

function openBotellaDetail(item: BotellaUnificadaItem): void {
  void router.push(botellaDetailPath(item.origen, item.id));
}

function onToggleSoloHuerfanas(): void {
  limpiarSeleccion();
  if (soloHuerfanas.value) {
    void reloadHuerfanasFromZero();
  }
}

function toggleSeleccion(clave: string): void {
  const next = new Set(seleccionadas.value);
  if (next.has(clave)) next.delete(clave);
  else next.add(clave);
  seleccionadas.value = next;
}

async function aplicarEstadoMasivo(): Promise<void> {
  if (seleccionadas.value.size === 0 || aplicandoEstadoMasivo.value) return;

  aplicandoEstadoMasivo.value = true;
  errorEstadoMasivo.value = '';
  try {
    const seleccion = Array.from(seleccionadas.value).map(parseClave);
    const respuesta = await updateBotellasEstadoMasivo(seleccion, estadoMasivoSeleccionado.value);
    if (respuesta.no_encontrados.length > 0) {
      errorEstadoMasivo.value = `${respuesta.no_encontrados.length} botella(s) ya no existían y no se actualizaron.`;
    }
    await reloadFromZero();
  } catch (err: unknown) {
    errorEstadoMasivo.value = err instanceof Error ? err.message : 'No se pudo actualizar el estado';
  } finally {
    aplicandoEstadoMasivo.value = false;
  }
}

function abrirAsociarIndividual(nId: number): void {
  nIdsParaAsociar.value = [nId];
  modalAsociarOpen.value = true;
}

async function handleAsociada(): Promise<void> {
  // Las Botellas recién asociadas ya no son huérfanas — recargar limpia la lista.
  nIdsParaAsociar.value = [];
  await reloadHuerfanasFromZero();
}

// El botón "Asociar a Cámara" de la barra masiva usa la selección actual, no una sola Botella —
// sólo huérfanas Cromo pasan por este modal, así que se descarta cualquier clave de otro origen.
watch(modalAsociarOpen, (isOpen) => {
  if (isOpen && nIdsParaAsociar.value.length === 0) {
    nIdsParaAsociar.value = Array.from(seleccionadas.value)
      .map(parseClave)
      .filter((clave) => clave.origen === 'cromo')
      .map((clave) => clave.id);
  }
});

onMounted(() => {
  void reloadFromZero();
});
</script>

<style scoped>
.botellas-view__header {
  padding: 22px 0 0;
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
  padding: 15px 0 14px;
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

.botellas-view__toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 65%, transparent);
  cursor: pointer;
  user-select: none;
}

.botellas-view__toggle input {
  accent-color: var(--color-accent);
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

/* El padding del scroll lo dibuja ViewerShell; sólo este viewer lo suma, de ahí el :deep. */
.botellas-view :deep(.viewer-shell__scroll) {
  padding: 12px 0 30px;
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

.botellas-view__list-row--huerfana {
  cursor: default;
}

.botellas-view__list-row--huerfana input[type='checkbox'] {
  flex: none;
  accent-color: var(--color-accent);
}

.botellas-view__bulk-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px -26px -14px;
  padding: 8px 0;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
}

.botellas-view__list-checkbox {
  flex: none;
  accent-color: var(--color-accent);
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
  color: inherit;
  text-decoration: none;
}

a.botellas-view__list-nombre:hover,
a.botellas-view__list-nombre:focus-visible {
  color: var(--color-accent);
  text-decoration: underline;
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

@media (max-width: 700px) {
  .botellas-view__toolbar-row {
    flex-wrap: wrap;
  }
}
</style>
