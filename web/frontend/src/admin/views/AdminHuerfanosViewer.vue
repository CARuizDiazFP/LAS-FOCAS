<!--
  Nombre de archivo: AdminHuerfanosViewer.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminHuerfanosViewer.vue
  Descripción: Dashboard /admin/servicios/viewer/Huerfanos — pelos de caminos residuales con causa sugerida y evidencia, normalizar/descartar en lote y auditoría global con progreso por SSE
-->
<template>
  <section class="huerfanos-viewer">
    <AdminPageHeader
      kicker="Panel admin · Viewer"
      title="Huérfanos"
      subtitle="Pelos con la etiqueta del Servicio en caminos que no son tramos suyos. Se revisan acá; sólo 'cable en desuso' se puede normalizar por ahora."
    />

    <div class="huerfanos-viewer__toolbar">
      <div class="huerfanos-viewer__toolbar-row">
        <label class="huerfanos-viewer__servicio">
          <span>Servicio (ID interno)</span>
          <input
            v-model="servicioTexto"
            type="search"
            inputmode="numeric"
            placeholder="Todos"
            @input="onServicioInput"
          />
        </label>

        <div class="huerfanos-viewer__chips">
          <span class="huerfanos-viewer__chips-label">Estado</span>
          <button
            v-for="opcion in estadosFiltro"
            :key="opcion.valor"
            type="button"
            :class="['huerfanos-viewer__chip', { 'is-active': filtroEstado === opcion.valor }]"
            @click="setEstado(opcion.valor)"
          >
            {{ opcion.label }}
          </button>
        </div>

        <button class="btn primary" type="button" :disabled="loading" @click="refrescar">
          <i class="ph ph-arrows-clockwise" aria-hidden="true"></i>
          Actualizar
        </button>
      </div>

      <div class="huerfanos-viewer__toolbar-row">
        <span class="huerfanos-viewer__chips-label">Causa</span>
        <button
          type="button"
          :class="['huerfanos-viewer__chip', { 'is-active': filtroCausa === '' }]"
          @click="setCausa('')"
        >
          Todas
        </button>
        <button
          v-for="causa in causas"
          :key="causa"
          type="button"
          :class="['huerfanos-viewer__chip', { 'is-active': filtroCausa === causa }]"
          @click="setCausa(causa)"
        >
          {{ causaHuerfanoLabel(causa) }}
          <span class="huerfanos-viewer__chip-count">{{ conteos[causa] ?? (loading ? '…' : '—') }}</span>
        </button>
        <span class="huerfanos-viewer__count">
          <strong>{{ total.toLocaleString('es-AR') }}</strong> huérfanos · mostrando {{ items.length }}
        </span>
      </div>

      <div class="huerfanos-viewer__toolbar-row huerfanos-viewer__acciones">
        <button
          class="btn primary"
          type="button"
          :disabled="accionando || seleccionNormalizable.length === 0"
          :title="'Sólo filas pendientes, no protegidas y con causa cable en desuso'"
          @click="normalizarSeleccion"
        >
          <i class="ph ph-scissors" aria-hidden="true"></i>
          Normalizar ({{ seleccionNormalizable.length }})
        </button>
        <button
          class="btn"
          type="button"
          :disabled="accionando || seleccionPendiente.length === 0"
          @click="descartarSeleccion"
        >
          <i class="ph ph-x-circle" aria-hidden="true"></i>
          Descartar ({{ seleccionPendiente.length }})
        </button>

        <span class="huerfanos-viewer__separador" aria-hidden="true"></span>

        <button
          class="btn"
          type="button"
          :disabled="auditoriaEnCurso || lanzando"
          @click="lanzarAuditoria"
        >
          <i class="ph ph-magnifying-glass-plus" aria-hidden="true"></i>
          Auditoría global
        </button>
        <span v-if="auditoria" class="huerfanos-viewer__auditoria">
          Corrida #{{ auditoria.id }} · {{ auditoria.estado }} ·
          {{ auditoria.leidas }}/{{ auditoria.total_objetivo ?? '?' }} servicios ·
          {{ auditoria.errores }} errores
          <template v-if="ultimoServicio"> · último: servicio {{ ultimoServicio }}</template>
        </span>
      </div>
    </div>

    <div v-if="error" class="huerfanos-viewer__inline-error">{{ error }}</div>
    <div v-if="mensaje" class="huerfanos-viewer__inline-ok">{{ mensaje }}</div>
    <div v-if="rechazados.length" class="huerfanos-viewer__rechazados" role="status">
      <strong>{{ rechazados.length }} fila(s) no se aplicaron:</strong>
      <ul>
        <li v-for="r in rechazados" :key="r.id">Fila {{ r.id }}: {{ r.motivo }}</li>
      </ul>
      <button type="button" class="btn subtle" @click="rechazados = []">Cerrar</button>
    </div>

    <div class="huerfanos-viewer__scroll">
      <table v-if="items.length > 0" class="huerfanos-viewer__tabla">
        <thead>
          <tr>
            <th class="huerfanos-viewer__check">
              <input
                type="checkbox"
                :checked="todosSeleccionados"
                aria-label="Seleccionar todos los pendientes"
                @change="toggleTodos"
              />
            </th>
            <th>Servicio</th>
            <th>Pelo</th>
            <th>Cable</th>
            <th>Causa</th>
            <th>Evidencia</th>
            <th>Estado</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td class="huerfanos-viewer__check">
              <input
                type="checkbox"
                :disabled="item.estado !== 'PENDIENTE'"
                :checked="seleccion.has(item.id)"
                :aria-label="`Seleccionar pelo ${item.pelo_n_id}`"
                @change="toggle(item.id)"
              />
            </td>
            <td>
              <button type="button" class="huerfanos-viewer__link" @click="filtrarServicio(item.servicio_id)">
                {{ item.servicio_numero }}
              </button>
              <span class="huerfanos-viewer__sub">ID {{ item.servicio_id }}</span>
            </td>
            <td>
              {{ item.pelo_n_id }}
              <span class="huerfanos-viewer__sub">
                {{ [item.numero_pelo ? `#${item.numero_pelo}` : null, item.color].filter(Boolean).join(' · ') }}
              </span>
            </td>
            <td>{{ item.cable_nombre ?? '—' }}</td>
            <td>
              <span :class="['huerfanos-viewer__causa', `is-${tokenCausa(item.causa)}`]">
                {{ causaHuerfanoLabel(item.causa) }}
              </span>
              <span v-if="item.protegido" class="huerfanos-viewer__protegido" :title="item.evidencia.motivo_proteccion ?? ''">
                <i class="ph ph-shield-check" aria-hidden="true"></i> Protegido
              </span>
            </td>
            <td class="huerfanos-viewer__evidencia">{{ evidenciaCompacta(item) }}</td>
            <td>
              <span :class="['huerfanos-viewer__estado', `is-${item.estado.toLowerCase()}`]">{{ item.estado }}</span>
              <span v-if="item.revisado_por" class="huerfanos-viewer__sub">{{ item.revisado_por }}</span>
            </td>
            <td class="huerfanos-viewer__acciones-fila">
              <template v-if="item.estado === 'PENDIENTE'">
                <button
                  v-if="item.normalizable"
                  type="button"
                  class="btn subtle"
                  :disabled="accionando"
                  @click="normalizar([item.id])"
                >
                  Normalizar
                </button>
                <button type="button" class="btn subtle" :disabled="accionando" @click="descartar([item.id])">
                  Descartar
                </button>
              </template>
              <span v-else class="huerfanos-viewer__sub">—</span>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-else-if="!loading" class="huerfanos-viewer__state-box">
        <i class="ph ph-check-circle" aria-hidden="true"></i>
        <h3>Sin huérfanos</h3>
        <p>Nada coincide con los filtros. Los huérfanos se registran al resolver los caminos de un Servicio o con la auditoría global.</p>
      </div>

      <div v-if="loading" class="huerfanos-viewer__loading-more">
        <i class="ph ph-circle-notch huerfanos-viewer__spin" aria-hidden="true"></i>
        Cargando...
      </div>

      <div v-if="hasMore && !loading" class="huerfanos-viewer__mas">
        <button type="button" class="btn" @click="loadNextPage">Cargar más</button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import AdminPageHeader from '../components/AdminPageHeader.vue';
import {
  CAUSAS_HUERFANO,
  causaHuerfanoLabel,
  descartarHuerfanos,
  lanzarAuditoriaGlobal,
  listarHuerfanos,
  normalizarHuerfanos,
  obtenerAuditoriaGlobal,
  streamUrlAuditoria,
  type CorridaAuditoria,
  type HuerfanoItem,
  type ResultadoRevisionHuerfanos,
} from '../../api/huerfanos';

const LIMIT = 100;

const route = useRoute();
const router = useRouter();

const causas = CAUSAS_HUERFANO;
const estadosFiltro = [
  { valor: 'PENDIENTE', label: 'Pendientes' },
  { valor: 'NORMALIZADO', label: 'Normalizados' },
  { valor: 'DESCARTADO', label: 'Descartados' },
  { valor: '', label: 'Todos' },
];

const items = ref<HuerfanoItem[]>([]);
const total = ref(0);
const conteos = ref<Record<string, number>>({});
const loading = ref(false);
const error = ref('');
const mensaje = ref('');
const rechazados = ref<{ id: number; motivo: string }[]>([]);
const offset = ref(0);
const hasMore = ref(false);
const filtroCausa = ref('');
const filtroEstado = ref('PENDIENTE');
const servicioTexto = ref(typeof route.query.servicio === 'string' ? route.query.servicio : '');
const seleccion = ref(new Set<number>());
const accionando = ref(false);

const auditoria = ref<CorridaAuditoria | null>(null);
const ultimoServicio = ref<number | null>(null);
const lanzando = ref(false);
const auditoriaEnCurso = computed(() => auditoria.value?.estado === 'EN_CURSO');

let eventSource: EventSource | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

const servicioId = computed<number | undefined>(() => {
  const n = Number.parseInt(servicioTexto.value.trim(), 10);
  return Number.isFinite(n) && n > 0 ? n : undefined;
});

const seleccionados = computed(() => items.value.filter((i) => seleccion.value.has(i.id)));
const seleccionPendiente = computed(() => seleccionados.value.filter((i) => i.estado === 'PENDIENTE'));
const seleccionNormalizable = computed(() => seleccionPendiente.value.filter((i) => i.normalizable));
const pendientesVisibles = computed(() => items.value.filter((i) => i.estado === 'PENDIENTE'));
const todosSeleccionados = computed(
  () => pendientesVisibles.value.length > 0 && pendientesVisibles.value.every((i) => seleccion.value.has(i.id)),
);

/** Token de color semántico: verde lo único normalizable, ámbar lo que sugiere daño, gris el resto. */
function tokenCausa(causa: string): 'ok' | 'warn' | 'idle' {
  if (causa === 'CABLE_DESUSO') return 'ok';
  if (causa === 'PELO_DANADO' || causa === 'CAMBIO_CABLE_DANO') return 'warn';
  return 'idle';
}

function evidenciaCompacta(item: HuerfanoItem): string {
  const s = item.evidencia.senales ?? {};
  const partes: string[] = [];
  if (item.evidencia.camino?.pelos != null) partes.push(`${item.evidencia.camino.pelos} pelos`);
  if (s.cables != null) partes.push(`${s.cables} cables`);
  if (s.cables_sin_uso) partes.push(`${s.cables_sin_uso} sin uso`);
  if (s.cables_compartidos_con_tramos) partes.push(`${s.cables_compartidos_con_tramos} compartidos c/tramo`);
  if (s.paralelo_a_tramo) partes.push('paralelo a tramo');
  if (s.botellas_fuera_de_tramos?.length) partes.push(`${s.botellas_fuera_de_tramos.length} botella(s) fuera de tramos`);
  if (item.evidencia.motivo_proteccion) partes.push(item.evidencia.motivo_proteccion);
  if (item.camino_semilla != null) partes.push(`semilla ${item.camino_semilla}`);
  return partes.join(' · ') || '—';
}

async function loadNextPage(): Promise<void> {
  if (loading.value) return;
  loading.value = true;
  error.value = '';
  try {
    const response = await listarHuerfanos({
      servicio_id: servicioId.value,
      causa: filtroCausa.value || undefined,
      estado: filtroEstado.value || undefined,
      limit: LIMIT,
      offset: offset.value,
    });
    total.value = response.total;
    conteos.value = response.conteos_por_causa;
    const vistos = new Set(items.value.map((i) => i.id));
    items.value.push(...response.items.filter((i) => !vistos.has(i.id)));
    offset.value += response.items.length;
    hasMore.value = response.items.length === LIMIT && offset.value < response.total;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo consultar los huérfanos';
  } finally {
    loading.value = false;
  }
}

async function reloadFromZero(): Promise<void> {
  items.value = [];
  total.value = 0;
  offset.value = 0;
  hasMore.value = false;
  seleccion.value = new Set();
  await loadNextPage();
}

function onServicioInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    void router.replace({ query: { ...route.query, servicio: servicioId.value ? String(servicioId.value) : undefined } });
    void reloadFromZero();
  }, 320);
}

function filtrarServicio(id: number): void {
  servicioTexto.value = String(id);
  onServicioInput();
}

function setCausa(valor: string): void {
  filtroCausa.value = filtroCausa.value === valor ? '' : valor;
  void reloadFromZero();
}

function setEstado(valor: string): void {
  filtroEstado.value = valor;
  void reloadFromZero();
}

function refrescar(): void {
  void reloadFromZero();
}

function toggle(id: number): void {
  const nuevo = new Set(seleccion.value);
  if (nuevo.has(id)) nuevo.delete(id);
  else nuevo.add(id);
  seleccion.value = nuevo;
}

function toggleTodos(): void {
  seleccion.value = todosSeleccionados.value ? new Set() : new Set(pendientesVisibles.value.map((i) => i.id));
}

async function aplicar(
  accion: (ids: number[]) => Promise<ResultadoRevisionHuerfanos>,
  ids: number[],
  verbo: string,
): Promise<void> {
  if (!ids.length) return;
  accionando.value = true;
  error.value = '';
  mensaje.value = '';
  rechazados.value = [];
  try {
    const resultado = await accion(ids);
    mensaje.value = `${resultado.aplicados.length} fila(s) ${verbo}.`;
    rechazados.value = resultado.rechazados;
    await reloadFromZero();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : `No se pudo completar: ${verbo}`;
  } finally {
    accionando.value = false;
  }
}

function normalizar(ids: number[]): Promise<void> {
  const ok = window.confirm(
    `Se van a excluir ${ids.length} pelo(s) de su Servicio (reversible con Restaurar en el panel del camino). ¿Continuar?`,
  );
  return ok ? aplicar(normalizarHuerfanos, ids, 'normalizadas') : Promise.resolve();
}

function descartar(ids: number[]): Promise<void> {
  return aplicar(descartarHuerfanos, ids, 'descartadas');
}

function normalizarSeleccion(): void {
  void normalizar(seleccionNormalizable.value.map((i) => i.id));
}

function descartarSeleccion(): void {
  void descartar(seleccionPendiente.value.map((i) => i.id));
}

// ── Auditoría global: progreso por el SSE de corridas ─────────────────────

function cerrarStream(): void {
  eventSource?.close();
  eventSource = null;
}

function conectarStream(corridaId: number): void {
  cerrarStream();
  const es = new EventSource(streamUrlAuditoria(corridaId));
  eventSource = es;
  es.addEventListener('inicio', (ev) => {
    const data = JSON.parse((ev as MessageEvent).data);
    if (auditoria.value) auditoria.value.total_objetivo = data.total_objetivo;
  });
  es.addEventListener('pagina', (ev) => {
    const data = JSON.parse((ev as MessageEvent).data);
    if (!auditoria.value) return;
    auditoria.value.leidas = data.leidas;
    auditoria.value.errores = data.errores;
    if (data.total != null) auditoria.value.total_objetivo = data.total;
    ultimoServicio.value = data.servicio_id ?? null;
  });
  es.addEventListener('resumen', (ev) => {
    const data = JSON.parse((ev as MessageEvent).data);
    if (auditoria.value) {
      auditoria.value.estado = data.estado;
      auditoria.value.leidas = data.leidas;
      auditoria.value.errores = data.errores;
    }
    cerrarStream();
    void reloadFromZero();
  });
  // Caída de la conexión (no el evento SSE "error" de negocio, que no se escucha acá): se cierra
  // el stream y se relee el estado real de la corrida; si sigue EN_CURSO, se reconecta.
  es.onerror = () => {
    cerrarStream();
    void cargarAuditoria();
  };
}

async function cargarAuditoria(): Promise<void> {
  try {
    const estado = await obtenerAuditoriaGlobal();
    auditoria.value = estado.corrida;
    if (estado.corrida?.estado === 'EN_CURSO') conectarStream(estado.corrida.id);
  } catch {
    // El estado de la auditoría es accesorio: el listado funciona igual.
  }
}

async function lanzarAuditoria(): Promise<void> {
  const ok = window.confirm(
    'La auditoría global resuelve en Cromo los caminos de los Servicios con más pelos (puede tardar horas). ¿Lanzarla?',
  );
  if (!ok) return;
  lanzando.value = true;
  error.value = '';
  try {
    const { corrida_id } = await lanzarAuditoriaGlobal();
    auditoria.value = {
      id: corrida_id,
      estado: 'EN_CURSO',
      total_objetivo: null,
      leidas: 0,
      actualizadas: 0,
      errores: 0,
      iniciada_at: null,
      finalizada_at: null,
    };
    conectarStream(corrida_id);
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo lanzar la auditoría global';
  } finally {
    lanzando.value = false;
  }
}

onMounted(async () => {
  await Promise.all([reloadFromZero(), cargarAuditoria()]);
});

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
  cerrarStream();
});
</script>

<style scoped>
.huerfanos-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.huerfanos-viewer__toolbar {
  padding: 4px 0 14px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.huerfanos-viewer__toolbar-row {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.huerfanos-viewer__servicio {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
  color: var(--color-neutral-500);
}

.huerfanos-viewer__servicio input {
  min-height: 34px;
  width: 160px;
  padding: 5px 10px;
  font-size: 13px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.huerfanos-viewer__chips {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  flex: 1;
}

.huerfanos-viewer__chips-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-neutral-500);
  margin-right: 2px;
}

.huerfanos-viewer__chip {
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

.huerfanos-viewer__chip:hover { border-color: var(--color-accent); }

.huerfanos-viewer__chip.is-active {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}

.huerfanos-viewer__chip-count {
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.huerfanos-viewer__count {
  margin-left: auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
  white-space: nowrap;
}

.huerfanos-viewer__count strong { color: var(--color-text); font-weight: 500; }

.huerfanos-viewer__separador {
  width: 1px;
  height: 22px;
  margin: 0 6px;
  background: var(--color-divider);
}

.huerfanos-viewer__auditoria {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.huerfanos-viewer__inline-error,
.huerfanos-viewer__inline-ok {
  margin-bottom: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 12.5px;
}

.huerfanos-viewer__inline-error {
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
}

.huerfanos-viewer__inline-ok {
  background: color-mix(in srgb, var(--color-state-ok) 14%, transparent);
  color: var(--color-state-ok);
}

.huerfanos-viewer__rechazados {
  margin: 0 0 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 12.5px;
  background: color-mix(in srgb, var(--color-state-warn) 14%, transparent);
  color: var(--color-state-warn);
}

.huerfanos-viewer__rechazados ul { margin: 6px 0 8px; padding-left: 18px; }

.huerfanos-viewer__scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.huerfanos-viewer__tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.huerfanos-viewer__tabla th {
  position: sticky;
  top: 0;
  z-index: 1;
  text-align: left;
  font-weight: 500;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 8px 10px;
  background: var(--color-surface);
  color: var(--color-neutral-500);
  border-bottom: 1px solid var(--color-divider);
}

.huerfanos-viewer__tabla td {
  padding: 8px 10px;
  vertical-align: top;
  border-bottom: 1px solid var(--color-neutral-800);
  color: var(--color-text);
}

.huerfanos-viewer__check { width: 28px; }

.huerfanos-viewer__sub {
  display: block;
  font-size: 11px;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.huerfanos-viewer__link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-accent-200);
  cursor: pointer;
  font: inherit;
}

.huerfanos-viewer__link:hover { text-decoration: underline; }

.huerfanos-viewer__causa {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  font-size: 11.5px;
  background: color-mix(in srgb, var(--color-state-idle) 16%, transparent);
  color: var(--color-text);
}

.huerfanos-viewer__causa.is-ok { background: color-mix(in srgb, var(--color-state-ok) 16%, transparent); }
.huerfanos-viewer__causa.is-warn { background: color-mix(in srgb, var(--color-state-warn) 16%, transparent); }

.huerfanos-viewer__protegido {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: 6px;
  font-size: 11px;
  color: var(--color-state-warn);
}

.huerfanos-viewer__evidencia {
  max-width: 360px;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.huerfanos-viewer__estado { font-size: 11.5px; font-weight: 500; }
.huerfanos-viewer__estado.is-pendiente { color: var(--color-state-warn); }
.huerfanos-viewer__estado.is-normalizado { color: var(--color-state-ok); }
.huerfanos-viewer__estado.is-descartado { color: var(--color-state-idle); }

.huerfanos-viewer__acciones-fila {
  white-space: nowrap;
  display: flex;
  gap: 6px;
}

.huerfanos-viewer__state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  max-width: 320px;
  margin: 34px auto;
  padding: 34px 22px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
  text-align: center;
}

.huerfanos-viewer__state-box i { font-size: 26px; color: var(--color-neutral-600); margin-bottom: 4px; }
.huerfanos-viewer__state-box h3 { font-size: 15px; font-weight: 500; margin: 0; }
.huerfanos-viewer__state-box p {
  font-size: 12.5px;
  line-height: 1.5;
  margin: 0;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.huerfanos-viewer__loading-more,
.huerfanos-viewer__mas {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.huerfanos-viewer__spin { font-size: 14px; animation: spin 1s linear infinite; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
