<!--
  Nombre de archivo: AdminServiciosSinOdfViewer.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminServiciosSinOdfViewer.vue
  Descripción: Dashboard /admin/servicios/viewer/ServiciosSinOdf — listado con scroll infinito de Servicios Activos sin ODF resuelta, chips de categoría con conteo real y modal de asociación manual
-->
<template>
  <ViewerShell
    bloque="servicios-sin-odf-viewer"
    :loading="loading"
    :error="error"
    :vacio="items.length === 0"
    :hay-mas="hasMore"
    texto-vacio="Ningún servicio coincide"
    texto-cargando="Cargando más servicios..."
    carga-inicial="caja"
    ancho-estado="260px"
    texto-carga-inicial="Cargando servicios..."
    @cargar-mas="cargarSiguiente"
  >
    <template #toolbar>
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
            <span class="servicios-sin-odf-viewer__chip-count">{{ conteos[categoria] ?? (loading ? '…' : '—') }}</span>
          </button>

          <span class="servicios-sin-odf-viewer__count">
            <strong>{{ total.toLocaleString('es-AR') }}</strong> servicios sin ODF · mostrando {{ items.length }}
          </span>
        </div>
      </div>
    </template>

    <div class="servicios-sin-odf-viewer__grid">
      <ServicioSinOdfCard
        v-for="item in items"
        :key="item.id"
        :servicio="item"
        @asociar="abrirModal"
        @resolver-path="abrirModalEnCamino"
      />
    </div>

    <template #vacio>
      <p>Probá con otro texto o quitá el filtro de categoría.</p>
    </template>

    <template #extra>
      <ModalAsociarOdf
        :open="modalOpen"
        :servicio-id="modalServicioId"
        :servicio-numero="modalServicioNumero"
        :iniciar-en-camino="modalIniciarEnCamino"
        @close="modalOpen = false"
        @asociado="handleAsociado"
        @error="handleModalError"
      />
    </template>
  </ViewerShell>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';

import AdminPageHeader from '../components/AdminPageHeader.vue';
import ModalAsociarOdf from '../../components/infra/ModalAsociarOdf.vue';
import ServicioSinOdfCard from '../../components/infra/ServicioSinOdfCard.vue';
import ViewerShell from '../../components/viewer/ViewerShell.vue';
import { usePaginatedSearch } from '../../composables/usePaginatedSearch';
import {
  CATEGORIAS_SERVICIO_SIN_ODF,
  categoriaServicioLabel,
  categoriaServicioToken,
  listarServiciosSinOdf,
  type ServicioSinOdfItem,
} from '../../api/serviciosOdf';

const categorias = CATEGORIAS_SERVICIO_SIN_ODF;

const query = ref('');
const filtroCategoria = ref('');

/** Conteo por categoría para los chips. Lo llena la respuesta del listado (`conteos_por_categoria`),
 * no un request propio. Arranca vacío, así que mientras carga la primera página los chips muestran
 * `…` y nunca un número inventado. */
const conteos = ref<Record<string, number>>({});

const {
  items,
  total,
  loading,
  error,
  hasMore,
  cargarSiguiente,
  recargarDesdeCero,
  recargarConDebounce,
} = usePaginatedSearch({
  limit: 60,
  cargarPagina: (offset, limit) =>
    listarServiciosSinOdf({
      q: query.value.trim(),
      categoria: filtroCategoria.value || undefined,
      limit,
      offset,
    }),
  claveItem: (item: ServicioSinOdfItem) => item.id,
  // Los conteos de los chips vienen EN esta misma respuesta (calculados en la misma pasada que
  // categoriza las filas, ver el docstring de `listar_servicios_sin_odf`) — antes eran 4
  // requests `limit: 0` extra, uno por categoría, disparados en paralelo con el listado en cada
  // montaje/búsqueda/refresco/asociación: 5 ejecuciones concurrentes de la query más cara de la
  // feature (~2891 filas candidatas, 145-275 ms) para devolver 4 enteros.
  // Son los mismos para cualquier página y para cualquier `categoria` (se calculan antes de ese
  // filtro), así que reasignarlos en cada página es un no-op salvo si cambia `q`.
  alRecibir: (respuesta) => {
    conteos.value = respuesta.conteos_por_categoria;
  },
  mensajeError: 'No se pudo consultar los Servicios sin ODF',
});

const modalOpen = ref(false);
const modalServicioId = ref<number | null>(null);
const modalServicioNumero = ref('');
const modalIniciarEnCamino = ref(false);

function onSearchInput(): void {
  recargarConDebounce();
}

function setCategoria(value: string): void {
  filtroCategoria.value = filtroCategoria.value === value ? '' : value;
  void recargarDesdeCero();
}

function refrescar(): void {
  void recargarDesdeCero();
}

function abrirModal(servicio: ServicioSinOdfItem): void {
  modalServicioId.value = servicio.id;
  modalServicioNumero.value = servicio.servicio_id;
  modalIniciarEnCamino.value = false;
  modalOpen.value = true;
}

/** El botón de la tarjeta es un atajo de navegación, no un segundo flujo: abre el mismo modal
 * pero ya en modo camino. La resolución la dispara el modal, nunca la grilla. */
function abrirModalEnCamino(servicio: ServicioSinOdfItem): void {
  modalServicioId.value = servicio.id;
  modalServicioNumero.value = servicio.servicio_id;
  modalIniciarEnCamino.value = true;
  modalOpen.value = true;
}

async function handleAsociado(): Promise<void> {
  modalOpen.value = false;
  // El Servicio recién asociado deja de aparecer en el listado (tiene override) — recargar
  // desde cero para no mostrar una fila resuelta como si siguiera pendiente. Los conteos de los
  // chips se actualizan solos: vienen en la respuesta del listado.
  await recargarDesdeCero();
}

function handleModalError(message: string): void {
  error.value = message;
}

onMounted(() => {
  void recargarDesdeCero();
});
</script>

<style scoped>
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

.servicios-sin-odf-viewer__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 11px;
}

@media (max-width: 1280px) { .servicios-sin-odf-viewer__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 1024px) { .servicios-sin-odf-viewer__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .servicios-sin-odf-viewer__grid { grid-template-columns: 1fr; } }
</style>
