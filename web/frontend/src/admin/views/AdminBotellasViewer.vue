<!--
  Nombre de archivo: AdminBotellasViewer.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminBotellasViewer.vue
  Descripción: Dashboard /admin/servicios/viewer/Botellas — listado dual grid/lista de Botellas (Cromo + legado) y detección de duplicados dentro de la misma Cámara padre
-->
<template>
  <section class="botellas-viewer">
    <AdminPageHeader
      kicker="Panel admin · Viewer"
      title="Botellas"
      subtitle="Listado de Botellas (Cromo + legado) y detección de candidatas a duplicado dentro de la misma Cámara padre."
    />

    <div class="botellas-viewer__toolbar">
      <div class="botellas-viewer__toolbar-row">
        <template v-if="!soloDuplicados">
          <div class="botellas-viewer__search">
            <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
            <input v-model="query" type="search" placeholder="Buscar por nombre" @input="onSearchInput" />
          </div>

          <label class="botellas-viewer__checkbox">
            <input v-model="incluirNoOperativas" type="checkbox" @change="reloadFromZero" />
            Mostrar no operativas
          </label>

          <div class="botellas-viewer__view-toggle" role="radiogroup" aria-label="Tipo de vista">
            <button
              type="button"
              role="radio"
              :aria-checked="vista === 'grid'"
              :class="['botellas-viewer__view-option', { 'is-active': vista === 'grid' }]"
              title="Vista grilla"
              @click="setVista('grid')"
            >
              <i class="ph ph-squares-four" aria-hidden="true"></i>
            </button>
            <button
              type="button"
              role="radio"
              :aria-checked="vista === 'list'"
              :class="['botellas-viewer__view-option', { 'is-active': vista === 'list' }]"
              title="Vista lista"
              @click="setVista('list')"
            >
              <i class="ph ph-rows" aria-hidden="true"></i>
            </button>
          </div>
        </template>

        <button
          type="button"
          :class="['botellas-viewer__chip', 'botellas-viewer__chip--duplicadas', { 'is-active': soloDuplicados }]"
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
          :disabled="loadingGrupos || gruposResolubles.length === 0"
          @click="abrirApropiacionMasiva"
        >
          <i class="ph ph-stack" aria-hidden="true"></i>
          Apropiación masiva
        </button>

        <button
          v-if="soloDuplicados"
          class="btn subtle"
          type="button"
          @click="abrirConsolidarManual"
        >
          <i class="ph ph-git-merge" aria-hidden="true"></i>
          Consolidar manualmente
        </button>

        <a class="btn subtle" :href="exportarBotellasInconsistenciasUrl()" target="_blank" rel="noopener">
          <i class="ph ph-file-xls" aria-hidden="true"></i>
          Exportar inconsistencias
        </a>
      </div>

      <div v-if="!soloDuplicados" class="botellas-viewer__toolbar-row">
        <span class="botellas-viewer__count">
          <strong>{{ total.toLocaleString('es-AR') }}</strong> botellas · mostrando {{ items.length }}
        </span>
      </div>

      <div v-else class="botellas-viewer__toolbar-row">
        <span class="botellas-viewer__count">
          <strong>{{ grupos.length }}</strong> grupo{{ grupos.length !== 1 ? 's' : '' }} candidato{{ grupos.length !== 1 ? 's' : '' }} a duplicado
        </span>
      </div>
    </div>

    <div v-if="error" class="botellas-viewer__inline-error">{{ error }}</div>

    <!-- Vista dual (listado general): grid/lista con scroll infinito -->
    <div v-if="!soloDuplicados" ref="scrollEl" class="botellas-viewer__scroll">
      <template v-if="items.length > 0">
        <div v-if="vista === 'grid'" class="botellas-viewer__grid">
          <BotellaViewerCard v-for="item in items" :key="`${item.origen}:${item.id}`" :botella="item" />
        </div>

        <div v-else class="botellas-viewer__list-layout">
          <div class="botellas-viewer__list">
            <div
              v-for="item in items"
              :key="`${item.origen}:${item.id}`"
              role="button"
              tabindex="0"
              :class="['botellas-viewer__list-row', { 'is-selected': selectedKey === `${item.origen}:${item.id}` }]"
              @click="selectedKey = `${item.origen}:${item.id}`"
              @keyup.enter="selectedKey = `${item.origen}:${item.id}`"
            >
              <span :class="['botellas-viewer__list-dot', `is-${estadoBotellaToken(item.estado)}`]" aria-hidden="true"></span>
              <span class="botellas-viewer__list-nombre">{{ item.nombre || `Botella ${item.id}` }}</span>
              <span :class="['botellas-viewer__origen-badge', `is-${item.origen}`]">{{ item.origen === 'legado' ? 'Legado' : 'Cromo' }}</span>
              <span class="botellas-viewer__list-estado">{{ item.estado }}</span>
            </div>
          </div>

          <aside v-if="selectedItem" class="botellas-viewer__preview">
            <span class="botellas-viewer__preview-kicker">Vista previa</span>
            <h2 class="botellas-viewer__preview-title">{{ selectedItem.nombre || `Botella ${selectedItem.id}` }}</h2>
            <div class="botellas-viewer__preview-tags">
              <span class="botellas-viewer__preview-tag is-accent">{{ selectedItem.estado }}</span>
              <span class="botellas-viewer__preview-tag">{{ selectedItem.origen === 'legado' ? 'Legado' : 'Cromo' }}</span>
            </div>
            <RouterLink class="btn primary" :to="botellaDetailPath(selectedItem.origen, selectedItem.id)">
              Abrir detalle completo
              <i class="ph ph-arrow-right" aria-hidden="true"></i>
            </RouterLink>
          </aside>
        </div>
      </template>

      <div v-else-if="!loading" class="botellas-viewer__state-box">
        <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        <h3>Ninguna botella coincide</h3>
        <p>Probá con otro nombre.</p>
      </div>

      <div v-if="loading && items.length > 0" class="botellas-viewer__loading-more">
        <i class="ph ph-circle-notch botellas-viewer__spin" aria-hidden="true"></i>
        Cargando más botellas...
      </div>

      <div ref="sentinel" class="botellas-viewer__sentinel" aria-hidden="true"></div>
    </div>

    <!-- Vista de duplicadas: tarjeta por grupo, agrupada por Cámara padre -->
    <div v-else class="botellas-viewer__scroll">
      <div v-if="loadingGrupos" class="botellas-viewer__state-box">
        <i class="ph ph-circle-notch botellas-viewer__spin" aria-hidden="true"></i>
        <h3>Calculando grupos...</h3>
      </div>

      <div v-else-if="errorGrupos" class="botellas-viewer__state-box is-error">
        <i class="ph ph-warning-circle" aria-hidden="true"></i>
        <h3>No se pudo calcular los duplicados</h3>
        <p>{{ errorGrupos }}</p>
      </div>

      <div v-else-if="grupos.length === 0" class="botellas-viewer__state-box">
        <i class="ph ph-check-circle" aria-hidden="true"></i>
        <h3>Sin candidatas a duplicado</h3>
        <p>No se detectaron Botellas hermanas con nombre normalizado coincidente.</p>
      </div>

      <div v-else class="botellas-viewer__grupos">
        <article v-for="grupo in grupos" :key="`${grupo.camara_padre_id}:${grupo.clave_normalizada}`" class="botellas-viewer__grupo-card">
          <header class="botellas-viewer__grupo-header">
            <strong>{{ grupo.camara_padre_nombre }}</strong>
            <span>{{ grupo.miembros.length }} botellas candidatas</span>
            <span v-if="grupo.estados_en_conflicto" class="botellas-viewer__grupo-badge">
              <i class="ph ph-warning" aria-hidden="true"></i>
              Estados distintos
            </span>
            <span v-if="!grupo.resoluble" class="botellas-viewer__grupo-badge is-manual">
              Revisión manual
            </span>
            <button
              v-if="!grupo.resoluble"
              class="btn subtle"
              type="button"
              @click="abrirConsolidarGrupo(grupo)"
            >
              Consolidar
            </button>
          </header>
          <div class="botellas-viewer__grupo-miembros">
            <div v-for="miembro in grupo.miembros" :key="`${miembro.origen}:${miembro.id}`" class="botellas-viewer__miembro-row">
              <span :class="['botellas-viewer__origen-badge', `is-${miembro.origen}`]">{{ miembro.origen === 'legado' ? 'Legado' : 'Cromo' }}</span>
              <span :class="['botellas-viewer__list-dot', `is-${estadoBotellaToken(miembro.estado)}`]" aria-hidden="true"></span>
              <span class="botellas-viewer__miembro-nombre">{{ miembro.nombre || `Botella ${miembro.id}` }}</span>
              <span v-if="miembro.tiene_cables" class="botellas-viewer__operativa-badge">
                <i class="ph ph-check-circle" aria-hidden="true"></i> Operativa
              </span>
              <span class="botellas-viewer__miembro-estado">{{ miembro.estado }}</span>
              <button
                v-if="grupo.resoluble && miembro.origen === 'legado'"
                class="btn subtle"
                type="button"
                @click="abrirApropiacion(grupo, miembro)"
              >
                Apropiar
              </button>
            </div>
          </div>
        </article>
      </div>
    </div>

    <ModalConsolidarBotellas
      :open="modalConsolidarOpen"
      :grupo="grupoParaConsolidar"
      @close="modalConsolidarOpen = false"
      @consolidado="handleConsolidado"
    />

    <ModalApropiarBotella
      :open="modalOpen"
      :legado-id="modalLegadoId"
      :legado-nombre="modalLegadoNombre"
      :cromo-n-id="modalCromoNId"
      :cromo-nombre="modalCromoNombre"
      :camara-padre-nombre="modalCamaraPadreNombre"
      @close="modalOpen = false"
      @apropiada="handleApropiada"
      @error="handleModalError"
    />

    <ModalConfirmarAccionMasiva
      :open="modalMasivaOpen"
      titulo="Apropiación masiva de Botellas duplicadas"
      :mensaje="mensajeApropiacionMasiva"
      :confirmando="confirmandoMasiva"
      :error="errorMasiva"
      :resultado="resultadoMasiva"
      @close="modalMasivaOpen = false"
      @confirm="confirmarApropiacionMasiva"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';

import AdminPageHeader from '../components/AdminPageHeader.vue';
import BotellaViewerCard from '../../components/infra/BotellaViewerCard.vue';
import ModalConfirmarAccionMasiva from '../../components/infra/ModalConfirmarAccionMasiva.vue';
import ModalApropiarBotella from '../../components/infra/ModalApropiarBotella.vue';
import ModalConsolidarBotellas from '../../components/infra/ModalConsolidarBotellas.vue';
import {
  apropiarMasivoBotellas,
  estadoBotellaToken,
  exportarBotellasInconsistenciasUrl,
  getBotellasDuplicados,
  getBotellasViewer,
  type BotellaDuplicadaItem,
  type BotellaUnificadaItem,
  type GrupoBotellasDuplicadas,
} from '../../api/botellas';
import { botellaDetailPath } from '../../utils/botellaLinks';

const LIMIT = 30;
const VISTA_STORAGE_KEY = 'botellas-admin-viewer.vista';

const query = ref('');
const incluirNoOperativas = ref(false);
const items = ref<BotellaUnificadaItem[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref('');
const offset = ref(0);
const hasMore = ref(true);
const sentinel = ref<HTMLElement | null>(null);
const scrollEl = ref<HTMLElement | null>(null);
const selectedKey = ref<string | null>(null);

const soloDuplicados = ref(false);
const grupos = ref<GrupoBotellasDuplicadas[]>([]);
const loadingGrupos = ref(false);
const errorGrupos = ref('');

const modalOpen = ref(false);
const modalLegadoId = ref<number | null>(null);
const modalLegadoNombre = ref('');
const modalCromoNId = ref<number | null>(null);
const modalCromoNombre = ref('');
const modalCamaraPadreNombre = ref('');

const modalMasivaOpen = ref(false);
const confirmandoMasiva = ref(false);
const errorMasiva = ref('');
const resultadoMasiva = ref<string | null>(null);

const modalConsolidarOpen = ref(false);
const grupoParaConsolidar = ref<GrupoBotellasDuplicadas | null>(null);

const vista = ref<'grid' | 'list'>(
  (localStorage.getItem(VISTA_STORAGE_KEY) as 'grid' | 'list' | null) === 'list' ? 'list' : 'grid',
);

const selectedItem = computed(
  () => items.value.find((item) => `${item.origen}:${item.id}` === selectedKey.value) ?? items.value[0] ?? null,
);

const gruposResolubles = computed(() => grupos.value.filter((g) => g.resoluble));

const mensajeApropiacionMasiva = computed(
  () =>
    `Esto apropiará automáticamente los ${gruposResolubles.value.length} grupos resolubles (1 Botella ` +
    'legado + 1 Cromo dentro del mismo padre): en cada uno, la Botella Cromo se conservará y la ' +
    'legado se eliminará físicamente tras reasignar sus datos reales a la Cámara padre. Los grupos ' +
    'que requieren revisión manual no se tocan. Esta acción no se puede deshacer.',
);

let observer: IntersectionObserver | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function mergeItems(next: BotellaUnificadaItem[]): void {
  const seen = new Set(items.value.map((item) => `${item.origen}:${item.id}`));
  for (const item of next) {
    const key = `${item.origen}:${item.id}`;
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
    const response = await getBotellasViewer({
      q: query.value.trim(),
      limit: LIMIT,
      offset: offset.value,
      incluirNoOperativas: incluirNoOperativas.value,
    });
    total.value = response.total;
    mergeItems(response.botellas);
    offset.value += response.botellas.length;
    hasMore.value = response.botellas.length === LIMIT && offset.value < response.total;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo consultar Botellas';
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
    const response = await getBotellasDuplicados();
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

function abrirApropiacion(grupo: GrupoBotellasDuplicadas, miembro: BotellaDuplicadaItem): void {
  const cromo = grupo.miembros.find((m) => m.origen === 'cromo');
  if (!cromo) return;
  modalLegadoId.value = miembro.id;
  modalLegadoNombre.value = miembro.nombre;
  modalCromoNId.value = cromo.id;
  modalCromoNombre.value = cromo.nombre;
  modalCamaraPadreNombre.value = grupo.camara_padre_nombre;
  modalOpen.value = true;
}

async function handleApropiada(): Promise<void> {
  modalOpen.value = false;
  await Promise.all([reloadDuplicados(), reloadFromZero()]);
}

function abrirApropiacionMasiva(): void {
  errorMasiva.value = '';
  resultadoMasiva.value = null;
  modalMasivaOpen.value = true;
}

async function confirmarApropiacionMasiva(): Promise<void> {
  confirmandoMasiva.value = true;
  errorMasiva.value = '';
  resultadoMasiva.value = null;
  try {
    const respuesta = await apropiarMasivoBotellas();
    resultadoMasiva.value =
      `${respuesta.grupos_apropiados} de ${respuesta.grupos_resolubles} grupos resolubles apropiados` +
      (respuesta.grupos_con_error > 0 ? ` — ${respuesta.grupos_con_error} con error.` : '.');
    await Promise.all([reloadDuplicados(), reloadFromZero()]);
  } catch (err: unknown) {
    errorMasiva.value = err instanceof Error ? err.message : 'No se pudo ejecutar la apropiación masiva.';
  } finally {
    confirmandoMasiva.value = false;
  }
}

function handleModalError(message: string): void {
  error.value = message;
}

function abrirConsolidarGrupo(grupo: GrupoBotellasDuplicadas): void {
  grupoParaConsolidar.value = grupo;
  modalConsolidarOpen.value = true;
}

function abrirConsolidarManual(): void {
  grupoParaConsolidar.value = null;
  modalConsolidarOpen.value = true;
}

async function handleConsolidado(): Promise<void> {
  await Promise.all([reloadDuplicados(), reloadFromZero()]);
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
.botellas-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.botellas-viewer__toolbar {
  padding: 4px 0 14px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.botellas-viewer__toolbar-row {
  display: flex;
  align-items: center;
  gap: 9px;
  flex-wrap: wrap;
}

.botellas-viewer__search {
  position: relative;
  flex: 1;
  min-width: 200px;
}

.botellas-viewer__search i {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-neutral-500);
  font-size: 15px;
  pointer-events: none;
}

.botellas-viewer__search input {
  width: 100%;
  min-height: 38px;
  padding: 6px 10px 6px 33px;
  font-size: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.botellas-viewer__checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
  white-space: nowrap;
  cursor: pointer;
}

.botellas-viewer__view-toggle {
  display: inline-flex;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.botellas-viewer__view-option {
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

.botellas-viewer__view-option:first-child { border-left: 0; }

.botellas-viewer__view-option.is-active {
  color: var(--color-accent);
  box-shadow: inset 0 0 0 1px var(--color-accent);
}

.botellas-viewer__chip {
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

.botellas-viewer__chip:hover { border-color: var(--color-accent); }

.botellas-viewer__chip.is-active {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}

.botellas-viewer__chip--duplicadas.is-active {
  border-color: var(--color-state-warn);
  background: color-mix(in srgb, var(--color-state-warn) 16%, transparent);
  color: var(--color-state-warn);
}

.botellas-viewer__count {
  margin-left: auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
  white-space: nowrap;
}

.botellas-viewer__count strong { color: var(--color-text); font-weight: 500; }

.botellas-viewer__inline-error {
  margin-bottom: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
  font-size: 12.5px;
}

.botellas-viewer__scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.botellas-viewer__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 11px;
}

@media (max-width: 1280px) { .botellas-viewer__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1024px) { .botellas-viewer__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .botellas-viewer__grid { grid-template-columns: 1fr; } }

.botellas-viewer__list-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 14px;
  align-items: start;
}

@media (max-width: 1100px) { .botellas-viewer__list-layout { grid-template-columns: 1fr; } }

.botellas-viewer__list {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.botellas-viewer__list-row {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 9px 11px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.15s ease;
}

.botellas-viewer__list-row:hover { background: color-mix(in srgb, var(--color-text) 5%, transparent); }

.botellas-viewer__list-row.is-selected {
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 40%, transparent);
}

.botellas-viewer__list-dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.botellas-viewer__list-dot.is-ok { background: var(--color-state-ok); }
.botellas-viewer__list-dot.is-warn { background: var(--color-state-warn); }
.botellas-viewer__list-dot.is-error { background: var(--color-state-error); }
.botellas-viewer__list-dot.is-idle { background: var(--color-state-idle); }

.botellas-viewer__list-nombre {
  flex: 1;
  min-width: 0;
  font-size: 13.5px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.botellas-viewer__list-estado {
  flex: none;
  width: 96px;
  text-align: right;
  font-size: 10.5px;
  letter-spacing: 0.04em;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.botellas-viewer__origen-badge {
  flex: none;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  letter-spacing: 0.04em;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.botellas-viewer__origen-badge.is-cromo {
  background: color-mix(in srgb, var(--color-accent) 16%, transparent);
  color: var(--color-accent-200);
}

.botellas-viewer__preview {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.botellas-viewer__preview-kicker {
  display: block;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.botellas-viewer__preview-title { margin: 5px 0 0; font-size: 18px; }

.botellas-viewer__preview-tags { display: flex; gap: 6px; flex-wrap: wrap; }

.botellas-viewer__preview-tag {
  padding: 3px 9px;
  border-radius: var(--radius-pill);
  font-size: 11px;
  border: 1px solid var(--color-divider);
  color: color-mix(in srgb, var(--color-text) 65%, transparent);
}

.botellas-viewer__preview-tag.is-accent {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.botellas-viewer__state-box {
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

.botellas-viewer__state-box i { font-size: 26px; color: var(--color-neutral-600); margin-bottom: 4px; }
.botellas-viewer__state-box h3 { font-size: 15px; font-weight: 500; margin: 0; }
.botellas-viewer__state-box p {
  font-size: 12.5px;
  line-height: 1.5;
  margin: 0;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.botellas-viewer__state-box.is-error { box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-error) 45%, transparent); }
.botellas-viewer__state-box.is-error i { color: var(--color-state-error); }

.botellas-viewer__loading-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.botellas-viewer__spin { font-size: 14px; animation: spin 1s linear infinite; }
.botellas-viewer__sentinel { height: 2px; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.botellas-viewer__grupos {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.botellas-viewer__grupo-card {
  padding: 14px;
  border-radius: var(--radius-lg);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.botellas-viewer__grupo-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  flex-wrap: wrap;
}

.botellas-viewer__grupo-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 9px;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-state-warn) 16%, transparent);
  color: var(--color-state-warn);
  font-size: 11px;
}

.botellas-viewer__grupo-badge.is-manual {
  background: color-mix(in srgb, var(--color-neutral-500) 20%, transparent);
  color: var(--color-neutral-100);
}

.botellas-viewer__grupo-miembros {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.botellas-viewer__miembro-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
}

.botellas-viewer__miembro-nombre {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.botellas-viewer__miembro-estado {
  flex: none;
  font-size: 10.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.botellas-viewer__operativa-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  font-size: 10px;
  background: color-mix(in srgb, var(--color-state-ok) 16%, transparent);
  color: var(--color-state-ok);
}
</style>
