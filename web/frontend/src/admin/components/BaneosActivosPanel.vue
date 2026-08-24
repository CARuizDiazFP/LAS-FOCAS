<!--
  Nombre de archivo: BaneosActivosPanel.vue
  Ubicación de archivo: web/frontend/src/admin/components/BaneosActivosPanel.vue
  Descripción: Tab "Baneos Activos" de /admin/Servicios/Baneos — listado de grupos baneados (Cámara padre + Botellas) y liberación masiva
-->
<template>
  <div class="card">
    <div class="activos-toolbar">
      <input
        v-model="q"
        type="search"
        placeholder="Buscar por nombre de cámara"
        class="input"
        style="flex:1;min-width:220px"
        @input="onSearchInput"
      />
      <span style="color:var(--muted);font-size:0.85rem">
        <strong>{{ total.toLocaleString('es-AR') }}</strong> grupo{{ total !== 1 ? 's' : '' }} baneado{{ total !== 1 ? 's' : '' }}
      </span>
    </div>

    <div v-if="cargando" style="color:var(--muted);padding:24px 0">Cargando grupos baneados…</div>
    <div v-else-if="error" style="color:var(--error);padding:16px 0">{{ error }}</div>
    <div v-else-if="grupos.length === 0" style="color:var(--muted);padding:24px 0">
      No hay grupos baneados{{ q.trim() ? ' que coincidan con la búsqueda.' : '.' }}
    </div>

    <table v-else class="table" style="width:100%">
      <thead>
        <tr>
          <th style="width:32px">
            <input
              type="checkbox"
              :checked="todosSeleccionadosPagina"
              aria-label="Seleccionar todos los grupos de esta página"
              @change="toggleSeleccionarTodos"
            />
          </th>
          <th>Cámara padre</th>
          <th>Botellas afectadas</th>
          <th>Motivo</th>
          <th>Usuario</th>
          <th>Fecha</th>
          <th>Estado</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="grupo in grupos" :key="grupo.camara_id">
          <td>
            <input
              type="checkbox"
              :checked="seleccionados.has(grupo.camara_id)"
              :aria-label="`Seleccionar grupo ${grupo.nombre}`"
              @change="toggleSeleccion(grupo.camara_id)"
            />
          </td>
          <td>
            <div>{{ grupo.nombre }}</div>
            <div v-if="grupo.direccion" style="font-size:0.8rem;color:var(--muted)">{{ grupo.direccion }}</div>
          </td>
          <td>
            <details v-if="grupo.botellas.length > 0">
              <summary style="cursor:pointer">{{ grupo.botellas_count }} botella{{ grupo.botellas_count !== 1 ? 's' : '' }}</summary>
              <ul style="margin:6px 0 0;padding-left:18px;font-size:0.82rem;color:var(--muted)">
                <li v-for="botella in grupo.botellas" :key="`${botella.origen}-${botella.id}`">
                  {{ botella.nombre }} <span style="opacity:0.7">({{ botella.estado }})</span>
                </li>
              </ul>
            </details>
            <span v-else style="color:var(--muted)">0 botellas</span>
          </td>
          <td style="font-size:0.85rem">{{ grupo.motivo || '—' }}</td>
          <td style="font-size:0.85rem">{{ grupo.usuario || '—' }}</td>
          <td style="font-size:0.85rem;color:var(--muted)">{{ grupo.fecha ? new Date(grupo.fecha).toLocaleString('es-AR') : '—' }}</td>
          <td>
            <span
              v-if="grupo.tiene_baneo_activo"
              class="activos-badge activos-badge--incidente"
              :title="`Necesita &quot;forzar&quot; o cerrarse desde el Protocolo de Protección (ticket ${grupo.ticket_baneo ?? 'sin ticket'})`"
            >
              🔒 Incidente {{ grupo.ticket_baneo ?? '' }}
            </span>
            <span
              v-if="grupo.estado_mixto"
              class="activos-badge activos-badge--mixto"
              title="Alguna Botella de este grupo tiene un estado distinto al de la Cámara padre"
            >
              ⚠️ Estado mixto
            </span>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="!cargando && !error && total > limit" class="activos-pagination">
      <button class="btn subtle" type="button" :disabled="offset === 0" @click="prevPage">‹ Anterior</button>
      <span style="color:var(--muted);font-size:0.85rem">
        Página {{ Math.floor(offset / limit) + 1 }} de {{ Math.max(1, Math.ceil(total / limit)) }}
      </span>
      <button class="btn subtle" type="button" :disabled="offset + limit >= total" @click="nextPage">Siguiente ›</button>
    </div>
  </div>

  <!-- Barra de acciones flotante -->
  <div v-if="seleccionados.size > 0" class="activos-bulk-panel" role="toolbar" aria-label="Acciones masivas de grupos baneados">
    <span style="font-weight:500;white-space:nowrap">{{ seleccionados.size }} seleccionado{{ seleccionados.size !== 1 ? 's' : '' }}</span>

    <textarea
      v-model="motivoLiberar"
      rows="1"
      placeholder="Motivo de la liberación (obligatorio)"
      class="activos-bulk-panel__motivo"
    />

    <label style="display:flex;align-items:center;gap:6px;white-space:nowrap;cursor:pointer">
      <input type="checkbox" v-model="forzar" />
      Forzar (incluye bloqueados por incidente activo)
    </label>

    <button class="btn primary" type="button" :disabled="!motivoLiberar.trim()" @click="abrirModalLiberar">
      Liberar seleccionados
    </button>
    <button class="btn subtle" type="button" @click="limpiarSeleccion">Deseleccionar todo</button>
  </div>

  <ModalConfirmarAccionMasiva
    :open="modalOpen"
    titulo="Liberar grupos baneados"
    :mensaje="mensajeLiberar"
    :confirmando="confirmandoLiberar"
    :error="errorLiberar"
    :resultado="resultadoLiberar"
    @close="modalOpen = false"
    @confirm="handleConfirmarLiberar"
  />
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { getGruposBaneados, liberarGruposMasivo, type GrupoBaneado } from '../api/admin';
import ModalConfirmarAccionMasiva from '../../components/infra/ModalConfirmarAccionMasiva.vue';

const limit = 25;

const grupos = ref<GrupoBaneado[]>([]);
const total = ref(0);
const q = ref('');
const offset = ref(0);
const cargando = ref(false);
const error = ref('');

const seleccionados = ref<Set<number>>(new Set());
const motivoLiberar = ref('');
const forzar = ref(false);

const modalOpen = ref(false);
const confirmandoLiberar = ref(false);
const errorLiberar = ref('');
const resultadoLiberar = ref<string | null>(null);

let debounceTimer: ReturnType<typeof setTimeout> | null = null;

const todosSeleccionadosPagina = computed(() =>
  grupos.value.length > 0 && grupos.value.every((g) => seleccionados.value.has(g.camara_id)),
);

// El resumen de "cuántos se omiten por incidente activo" sólo puede calcularse sobre los grupos
// de la página actual (`grupos`) — si la selección incluye ids de otras páginas, esos no aportan
// al conteo de bloqueados que se muestra en el modal (el backend sigue aplicando el guard real).
const gruposSeleccionadosPagina = computed(() => grupos.value.filter((g) => seleccionados.value.has(g.camara_id)));

const mensajeLiberar = computed(() => {
  const totalSel = seleccionados.value.size;
  const base = `Se van a liberar ${totalSel} grupo${totalSel !== 1 ? 's' : ''} baneado${totalSel !== 1 ? 's' : ''}.`;
  const bloqueados = gruposSeleccionadosPagina.value.filter((g) => g.tiene_baneo_activo);
  if (bloqueados.length === 0) return base;
  if (forzar.value) {
    const nombres = bloqueados
      .map((g) => `${g.nombre}${g.ticket_baneo ? ` (ticket ${g.ticket_baneo})` : ''}`)
      .join(', ');
    return `${base} ⚠️ Vas a FORZAR la liberación de ${bloqueados.length} grupo${bloqueados.length !== 1 ? 's' : ''} con un incidente activo del Protocolo de Protección: ${nombres}.`;
  }
  return `${base} ${bloqueados.length} de los seleccionados tiene${bloqueados.length !== 1 ? 'n' : ''} un incidente activo del Protocolo de Protección y se omitirá${bloqueados.length !== 1 ? 'n' : ''} (activá "Forzar" para incluirlos).`;
});

async function cargar(): Promise<void> {
  cargando.value = true;
  error.value = '';
  try {
    const respuesta = await getGruposBaneados({ q: q.value.trim() || undefined, limit, offset: offset.value });
    grupos.value = respuesta.grupos;
    total.value = respuesta.total;
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'No se pudo obtener el listado de grupos baneados.';
  } finally {
    cargando.value = false;
  }
}

function onSearchInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    offset.value = 0;
    void cargar();
  }, 300);
}

function prevPage(): void {
  if (offset.value === 0) return;
  offset.value = Math.max(0, offset.value - limit);
  void cargar();
}

function nextPage(): void {
  if (offset.value + limit >= total.value) return;
  offset.value += limit;
  void cargar();
}

function toggleSeleccion(camaraId: number): void {
  const next = new Set(seleccionados.value);
  if (next.has(camaraId)) next.delete(camaraId);
  else next.add(camaraId);
  seleccionados.value = next;
}

function toggleSeleccionarTodos(): void {
  const next = new Set(seleccionados.value);
  if (todosSeleccionadosPagina.value) {
    for (const g of grupos.value) next.delete(g.camara_id);
  } else {
    for (const g of grupos.value) next.add(g.camara_id);
  }
  seleccionados.value = next;
}

function limpiarSeleccion(): void {
  seleccionados.value = new Set();
}

function abrirModalLiberar(): void {
  errorLiberar.value = '';
  resultadoLiberar.value = null;
  modalOpen.value = true;
}

async function handleConfirmarLiberar(): Promise<void> {
  confirmandoLiberar.value = true;
  errorLiberar.value = '';
  resultadoLiberar.value = null;
  try {
    const respuesta = await liberarGruposMasivo([...seleccionados.value], motivoLiberar.value.trim(), forzar.value);
    resultadoLiberar.value =
      `${respuesta.liberados} de ${respuesta.total_solicitados} grupo${respuesta.total_solicitados !== 1 ? 's' : ''} liberado${respuesta.liberados !== 1 ? 's' : ''}` +
      (respuesta.omitidos > 0 ? ` — ${respuesta.omitidos} omitido${respuesta.omitidos !== 1 ? 's' : ''}.` : '.');
    limpiarSeleccion();
    motivoLiberar.value = '';
    forzar.value = false;
    await cargar();
  } catch (e: unknown) {
    errorLiberar.value = e instanceof Error ? e.message : 'No se pudieron liberar los grupos.';
  } finally {
    confirmandoLiberar.value = false;
  }
}

onMounted(() => {
  void cargar();
});
</script>

<style scoped>
.activos-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.activos-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 16px;
}

.activos-badge {
  display: inline-block;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 600;
  white-space: nowrap;
}

.activos-badge + .activos-badge {
  margin-left: 6px;
}

.activos-badge--incidente {
  background: color-mix(in srgb, var(--error) 15%, transparent);
  color: var(--error);
  border: 1px solid color-mix(in srgb, var(--error) 33%, transparent);
}

.activos-badge--mixto {
  background: color-mix(in srgb, var(--warning) 15%, transparent);
  color: var(--warning);
  border: 1px solid color-mix(in srgb, var(--warning) 33%, transparent);
}

.activos-bulk-panel {
  position: fixed;
  left: 50%;
  bottom: 22px;
  transform: translateX(-50%);
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 12.5px;
  color: var(--text);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  flex-wrap: wrap;
  max-width: calc(100vw - 32px);
}

.activos-bulk-panel__motivo {
  flex: 1;
  min-width: 220px;
  max-width: 360px;
  resize: vertical;
  padding: 6px 8px;
  font-size: 12.5px;
  background: var(--color-surface-2, var(--color-surface));
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--text);
}

@media (max-width: 700px) {
  .activos-bulk-panel {
    left: 12px;
    right: 12px;
    bottom: 12px;
    transform: none;
  }
}
</style>
