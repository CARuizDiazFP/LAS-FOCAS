<!--
  Nombre de archivo: AdminInconsistenciasCromoViewer.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminInconsistenciasCromoViewer.vue
  Descripción: Dashboard /admin/servicios/viewer/InconsistenciasCromo — casos de inconsistencias de Cromo (isla de fusiones, cable sin extremo, elemento isla) con revisión manual en lote (cuarentena, aceptar, reportar, liberar) y detección manual con progreso por SSE
-->
<template>
  <section class="inconsistencias-viewer">
    <AdminPageHeader
      kicker="Panel admin · Viewer"
      title="Inconsistencias de Cromo"
      subtitle="Pelos en uso cuyo camino no cierra (fusiones sin continuación, cables sin extremo). Lo seguro entra solo en cuarentena (deja de contar como uso); lo ambiguo o con ODF se revisa acá."
    />

    <nav class="inconsistencias-viewer__tabs" role="tablist" aria-label="Secciones del viewer">
      <button
        v-for="t in pestanas"
        :key="t.valor"
        type="button"
        role="tab"
        :aria-selected="pestana === t.valor"
        :class="['inconsistencias-viewer__tab', { 'is-active': pestana === t.valor }]"
        @click="setPestana(t.valor)"
      >
        {{ t.label }}
      </button>
    </nav>

    <PropuestasArbitroPanel v-if="pestana === 'propuestas'" />
    <ReglasArbitroPanel v-else-if="pestana === 'reglas'" />

    <template v-else>
    <div class="inconsistencias-viewer__toolbar">
      <div class="inconsistencias-viewer__toolbar-row">
        <label class="inconsistencias-viewer__servicio">
          <span>Servicio (ID interno)</span>
          <input v-model="servicioTexto" type="search" inputmode="numeric" placeholder="Todos" @input="onFiltroTextoInput" />
        </label>
        <label class="inconsistencias-viewer__localidad">
          <span>Localidad</span>
          <input v-model="localidadTexto" type="search" placeholder="Todas" @input="onFiltroTextoInput" />
        </label>

        <div class="inconsistencias-viewer__chips">
          <span class="inconsistencias-viewer__chips-label">Estado</span>
          <button
            v-for="opcion in estadosFiltro"
            :key="opcion.valor"
            type="button"
            :class="['inconsistencias-viewer__chip', { 'is-active': filtroEstado === opcion.valor }]"
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

      <div class="inconsistencias-viewer__toolbar-row">
        <span class="inconsistencias-viewer__chips-label">Revisión</span>
        <button
          v-for="opcion in revisionesFiltro"
          :key="opcion.valor"
          type="button"
          :class="['inconsistencias-viewer__chip', { 'is-active': filtroRevision === opcion.valor }]"
          @click="setRevision(opcion.valor)"
        >
          {{ opcion.label }}
        </button>
        <span class="inconsistencias-viewer__separador" aria-hidden="true"></span>
        <span class="inconsistencias-viewer__chips-label">Tipo</span>
        <button
          type="button"
          :class="['inconsistencias-viewer__chip', { 'is-active': filtroTipo === '' }]"
          @click="setTipo('')"
        >
          Todos
        </button>
        <button
          v-for="tipo in tipos"
          :key="tipo"
          type="button"
          :class="['inconsistencias-viewer__chip', { 'is-active': filtroTipo === tipo }]"
          @click="setTipo(tipo)"
        >
          {{ tipoInconsistenciaLabel(tipo) }}
          <span class="inconsistencias-viewer__chip-count">{{ conteos[tipo] ?? (loading ? '…' : 0) }}</span>
        </button>
        <span class="inconsistencias-viewer__count">
          <strong>{{ total.toLocaleString('es-AR') }}</strong> casos · mostrando {{ items.length }}
        </span>
      </div>

      <div class="inconsistencias-viewer__toolbar-row inconsistencias-viewer__acciones">
        <button
          class="btn primary"
          type="button"
          :disabled="accionando || seleccion.size === 0"
          title="Los pelos del caso dejan de contar como uso de sus servicios"
          @click="aplicarSeleccion('CUARENTENA')"
        >
          <i class="ph ph-prohibit" aria-hidden="true"></i>
          Cuarentena ({{ seleccion.size }})
        </button>
        <button class="btn" type="button" :disabled="accionando || seleccion.size === 0" @click="aplicarSeleccion('ACEPTADA')">
          <i class="ph ph-check-circle" aria-hidden="true"></i>
          Aceptar ({{ seleccion.size }})
        </button>
        <button class="btn" type="button" :disabled="accionando || seleccion.size === 0" @click="aplicarSeleccion('REPORTADA')">
          <i class="ph ph-paper-plane-tilt" aria-hidden="true"></i>
          Reportada ({{ seleccion.size }})
        </button>
        <button class="btn" type="button" :disabled="accionando || seleccion.size === 0" @click="aplicarSeleccion('PENDIENTE')">
          <i class="ph ph-arrow-counter-clockwise" aria-hidden="true"></i>
          Liberar ({{ seleccion.size }})
        </button>

        <span class="inconsistencias-viewer__separador" aria-hidden="true"></span>

        <button class="btn" type="button" :disabled="exportando" @click="exportarXlsx">
          <i class="ph ph-file-xls" aria-hidden="true"></i>
          Exportar XLSX
        </button>

        <button class="btn" type="button" :disabled="deteccionEnCurso || lanzando" @click="lanzarDeteccionManual">
          <i class="ph ph-magnifying-glass-plus" aria-hidden="true"></i>
          Detectar ahora
        </button>
        <span v-if="deteccion" class="inconsistencias-viewer__deteccion">
          Corrida #{{ deteccion.id }} · {{ deteccion.estado }} ·
          <template v-if="faseActual">{{ faseActual }} · </template>
          {{ deteccion.leidas }}/{{ deteccion.total_objetivo ?? '?' }} fases ·
          {{ deteccion.errores }} errores
        </span>
        <ul v-if="erroresDeteccion.length" class="inconsistencias-viewer__errores-deteccion">
          <li v-for="(e, i) in erroresDeteccion" :key="i">{{ e }}</li>
        </ul>
      </div>
    </div>

    <details class="inconsistencias-viewer__aviso">
      <summary>Aviso de casos nuevos a Slack</summary>
      <form class="inconsistencias-viewer__aviso-form" @submit.prevent="guardarAviso">
        <label>
          Canales (separados por coma, ej. #cromo-alertas)
          <input v-model="avisoCanales" type="text" maxlength="512" placeholder="#canal,C0123456789" />
        </label>
        <label class="inconsistencias-viewer__aviso-check">
          <input v-model="avisoActivo" type="checkbox" />
          Activo
        </label>
        <button class="btn" type="submit" :disabled="guardandoAviso">Guardar</button>
      </form>
    </details>

    <div v-if="error" class="inconsistencias-viewer__inline-error">{{ error }}</div>
    <div v-if="mensaje" class="inconsistencias-viewer__inline-ok">{{ mensaje }}</div>
    <div v-if="rechazados.length" class="inconsistencias-viewer__rechazados" role="status">
      <strong>{{ rechazados.length }} caso(s) no se aplicaron:</strong>
      <ul>
        <li v-for="r in rechazados" :key="r.id">Caso {{ r.id }}: {{ r.motivo }}</li>
      </ul>
      <button type="button" class="btn subtle" @click="rechazados = []">Cerrar</button>
    </div>

    <div class="inconsistencias-viewer__scroll">
      <table v-if="items.length > 0" class="inconsistencias-viewer__tabla">
        <thead>
          <tr>
            <th class="inconsistencias-viewer__check">
              <input
                type="checkbox"
                :checked="todosSeleccionados"
                aria-label="Seleccionar todos los casos visibles"
                @change="toggleTodos"
              />
            </th>
            <th>Tipo</th>
            <th>Revisión</th>
            <th>Estado</th>
            <th>Objeto</th>
            <th>Localidad</th>
            <th>Afectados</th>
            <th>Motivo / evidencia</th>
            <th>Primera / última vez</th>
            <th>Acción</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in items" :key="item.id">
            <td class="inconsistencias-viewer__check">
              <input
                type="checkbox"
                :disabled="!esEditable(item)"
                :checked="seleccion.has(item.id)"
                :aria-label="`Seleccionar caso ${item.id}`"
                @change="toggle(item.id)"
              />
            </td>
            <td><span class="inconsistencias-viewer__tipo">{{ tipoInconsistenciaLabel(item.tipo) }}</span></td>
            <td>
              <span :class="['inconsistencias-viewer__revision', `is-${item.revision.toLowerCase()}`]">
                {{ item.revision === 'AUTO' ? 'Automática' : 'Manual' }}
              </span>
            </td>
            <td>
              <span :class="['inconsistencias-viewer__estado', `is-${item.estado.toLowerCase()}`]">{{ item.estado }}</span>
              <span v-if="item.actualizado_por" class="inconsistencias-viewer__sub">{{ item.actualizado_por }}</span>
            </td>
            <td>
              {{ item.nombre ?? '—' }}
              <span class="inconsistencias-viewer__sub">n_id {{ item.objeto_n_id }}</span>
            </td>
            <td>{{ item.localidad ?? '—' }}</td>
            <td>
              {{ item.pelos }} pelo(s)
              <span class="inconsistencias-viewer__sub">{{ item.servicios }} servicio(s)</span>
            </td>
            <td class="inconsistencias-viewer__evidencia">{{ evidenciaCompacta(item) }}</td>
            <td class="inconsistencias-viewer__sub-celda">
              {{ fecha(item.primera_vez) }}
              <span class="inconsistencias-viewer__sub">{{ fecha(item.ultima_vez) }}</span>
            </td>
            <td class="inconsistencias-viewer__acciones-fila">
              <template v-if="esEditable(item)">
                <button
                  v-if="item.estado !== 'CUARENTENA'"
                  type="button"
                  class="btn subtle"
                  :disabled="accionando"
                  @click="aplicar([item.id], 'CUARENTENA')"
                >
                  Cuarentena
                </button>
                <button
                  v-if="item.estado !== 'ACEPTADA'"
                  type="button"
                  class="btn subtle"
                  :disabled="accionando"
                  @click="aplicar([item.id], 'ACEPTADA')"
                >
                  Aceptar
                </button>
                <button
                  v-if="item.estado !== 'REPORTADA'"
                  type="button"
                  class="btn subtle"
                  :disabled="accionando"
                  @click="aplicar([item.id], 'REPORTADA')"
                >
                  Reportada
                </button>
                <button
                  v-if="item.estado !== 'PENDIENTE'"
                  type="button"
                  class="btn subtle"
                  :disabled="accionando"
                  @click="aplicar([item.id], 'PENDIENTE')"
                >
                  Liberar
                </button>
              </template>
              <span v-else class="inconsistencias-viewer__sub">—</span>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-else-if="!loading" class="inconsistencias-viewer__state-box">
        <i class="ph ph-check-circle" aria-hidden="true"></i>
        <h3>Sin casos</h3>
        <p>Nada coincide con los filtros. Los casos se registran al correr la detección (después de cada ingesta o con "Detectar ahora").</p>
      </div>

      <div v-if="loading" class="inconsistencias-viewer__loading-more">
        <i class="ph ph-circle-notch inconsistencias-viewer__spin" aria-hidden="true"></i>
        Cargando...
      </div>

      <div v-if="hasMore && !loading" class="inconsistencias-viewer__mas">
        <button type="button" class="btn" @click="loadNextPage">Cargar más</button>
      </div>
    </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import AdminPageHeader from '../components/AdminPageHeader.vue';
import PropuestasArbitroPanel from '../components/arbitro/PropuestasArbitroPanel.vue';
import ReglasArbitroPanel from '../components/arbitro/ReglasArbitroPanel.vue';
import {
  TIPOS_INCONSISTENCIA,
  cambiarEstadoInconsistencias,
  exportarInconsistencias,
  guardarAvisoSlack,
  lanzarDeteccion,
  listarInconsistencias,
  obtenerAvisoSlack,
  obtenerDeteccion,
  tipoInconsistenciaLabel,
  type CorridaDeteccion,
  type EstadoDestinoInconsistencia,
  type InconsistenciaItem,
} from '../../api/inconsistenciasCromo';
import { useAdminNotifications } from '../../composables/useAdminNotifications';
import { useCorridaSse } from '../../composables/useCorridaSse';

const LIMIT = 100;

type Pestana = 'casos' | 'propuestas' | 'reglas';
const pestanas: { valor: Pestana; label: string }[] = [
  { valor: 'casos', label: 'Casos' },
  { valor: 'propuestas', label: 'Propuestas' },
  { valor: 'reglas', label: 'Reglas' },
];

const route = useRoute();
const router = useRouter();

const tipos = TIPOS_INCONSISTENCIA;
const estadosFiltro = [
  { valor: 'PENDIENTE', label: 'Pendientes' },
  { valor: 'CUARENTENA', label: 'Cuarentena' },
  { valor: 'REPORTADA', label: 'Reportadas' },
  { valor: 'ACEPTADA', label: 'Aceptadas' },
  { valor: 'CORREGIDA', label: 'Corregidas' },
  { valor: '', label: 'Todos' },
];
const revisionesFiltro = [
  { valor: '', label: 'Todas' },
  { valor: 'MANUAL', label: 'Manual' },
  { valor: 'AUTO', label: 'Automática' },
];
const ACCIONES: Record<EstadoDestinoInconsistencia, { verbo: string; confirmar?: string }> = {
  CUARENTENA: {
    verbo: 'puestos en cuarentena',
    confirmar: 'Los pelos de {n} caso(s) dejarán de contar como uso de sus servicios. ¿Continuar?',
  },
  ACEPTADA: { verbo: 'aceptados' },
  REPORTADA: { verbo: 'marcados como reportados' },
  PENDIENTE: {
    verbo: 'liberados a pendiente',
    confirmar: '{n} caso(s) vuelven a pendiente; si estaban en cuarentena sus pelos vuelven a contar como uso. ¿Continuar?',
  },
};

const pestana = ref<Pestana>(
  route.query.tab === 'propuestas' || route.query.tab === 'reglas' ? route.query.tab : 'casos',
);

function setPestana(valor: Pestana): void {
  pestana.value = valor;
  void router.replace({ query: { ...route.query, tab: valor === 'casos' ? undefined : valor } });
}

const items = ref<InconsistenciaItem[]>([]);
const total = ref(0);
const conteos = ref<Record<string, number>>({});
const loading = ref(false);
const error = ref('');
const mensaje = ref('');
const rechazados = ref<{ id: number; motivo: string }[]>([]);
const offset = ref(0);
const hasMore = ref(false);
const filtroTipo = ref('');
const filtroEstado = ref('PENDIENTE');
const filtroRevision = ref('');
const servicioTexto = ref(typeof route.query.servicio_id === 'string' ? route.query.servicio_id : '');
const localidadTexto = ref(typeof route.query.localidad === 'string' ? route.query.localidad : '');
const seleccion = ref(new Set<number>());
const accionando = ref(false);

// Con un servicio en la URL (enlace del panel Camino) se muestran todos los estados.
if (servicioTexto.value) filtroEstado.value = '';

const deteccion = ref<CorridaDeteccion | null>(null);
const faseActual = ref('');
const lanzando = ref(false);
const erroresDeteccion = ref<string[]>([]);
const deteccionEnCurso = computed(() => deteccion.value?.estado === 'EN_CURSO');
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

const servicioId = computed<number | undefined>(() => {
  const n = Number.parseInt(servicioTexto.value.trim(), 10);
  return Number.isFinite(n) && n > 0 ? n : undefined;
});

/** CORREGIDA la pone sólo el detector: no se edita a mano. */
function esEditable(item: InconsistenciaItem): boolean {
  return item.estado !== 'CORREGIDA';
}

const editablesVisibles = computed(() => items.value.filter(esEditable));
const todosSeleccionados = computed(
  () => editablesVisibles.value.length > 0 && editablesVisibles.value.every((i) => seleccion.value.has(i.id)),
);

function fecha(valor: string | null): string {
  if (!valor) return '—';
  const d = new Date(valor);
  return Number.isNaN(d.getTime()) ? valor : d.toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' });
}

/** Motivo + lo más útil de la evidencia, en una línea. */
function evidenciaCompacta(item: InconsistenciaItem): string {
  const e = item.evidencia ?? {};
  const partes: string[] = [];
  if (e.motivo) partes.push(e.motivo.replace(/_/g, ' '));
  if (e.contenedor?.nombre) partes.push(`${e.contenedor.es_odf ? 'ODF' : 'botella'} ${e.contenedor.nombre}`);
  if (e.elemento_conocido) partes.push(e.elemento_conocido);
  const cables = (e.cables ?? []).map((c) => c.nombre).filter(Boolean);
  if (cables.length) partes.push(`cables ${cables.slice(0, 3).join(', ')}${cables.length > 3 ? '…' : ''}`);
  const servicios = e.servicios ?? [];
  if (servicios.length) partes.push(`servicios ${servicios.slice(0, 3).join(', ')}${servicios.length > 3 ? '…' : ''}`);
  return partes.join(' · ') || '—';
}

async function loadNextPage(): Promise<void> {
  if (loading.value) return;
  loading.value = true;
  error.value = '';
  try {
    const response = await listarInconsistencias({
      tipo: filtroTipo.value || undefined,
      estado: filtroEstado.value || undefined,
      revision: filtroRevision.value || undefined,
      localidad: localidadTexto.value.trim() || undefined,
      servicio_id: servicioId.value,
      limit: LIMIT,
      offset: offset.value,
    });
    total.value = response.total;
    conteos.value = response.conteos_por_tipo;
    const vistos = new Set(items.value.map((i) => i.id));
    items.value.push(...response.items.filter((i) => !vistos.has(i.id)));
    offset.value += response.items.length;
    hasMore.value = response.items.length === LIMIT && offset.value < response.total;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo consultar las inconsistencias';
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

function onFiltroTextoInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    void router.replace({
      query: {
        ...route.query,
        servicio_id: servicioId.value ? String(servicioId.value) : undefined,
        localidad: localidadTexto.value.trim() || undefined,
      },
    });
    void reloadFromZero();
  }, 320);
}

function setTipo(valor: string): void {
  filtroTipo.value = filtroTipo.value === valor ? '' : valor;
  void reloadFromZero();
}

function setEstado(valor: string): void {
  filtroEstado.value = valor;
  void reloadFromZero();
}

function setRevision(valor: string): void {
  filtroRevision.value = valor;
  void reloadFromZero();
}

const exportando = ref(false);

const avisoCanales = ref('');
const avisoActivo = ref(false);
const guardandoAviso = ref(false);

async function cargarAviso(): Promise<void> {
  try {
    const cfg = await obtenerAvisoSlack();
    avisoCanales.value = cfg.slack_channels;
    avisoActivo.value = cfg.activo;
  } catch {
    // Opcional: si no carga, el panel queda vacío y el guardado muestra el error real.
  }
}

async function guardarAviso(): Promise<void> {
  if (guardandoAviso.value) return;
  guardandoAviso.value = true;
  error.value = '';
  try {
    const cfg = await guardarAvisoSlack({ slack_channels: avisoCanales.value, activo: avisoActivo.value });
    avisoCanales.value = cfg.slack_channels;
    avisoActivo.value = cfg.activo;
    mensaje.value = 'Aviso a Slack guardado.';
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo guardar el aviso a Slack';
  } finally {
    guardandoAviso.value = false;
  }
}

/** XLSX con los filtros activos; sin filtro de estado exporta sólo lo accionable. */
async function exportarXlsx(): Promise<void> {
  if (exportando.value) return;
  exportando.value = true;
  error.value = '';
  try {
    await exportarInconsistencias({
      tipo: filtroTipo.value || undefined,
      estado: filtroEstado.value || undefined,
      revision: filtroRevision.value || undefined,
      localidad: localidadTexto.value.trim() || undefined,
      servicio_id: servicioId.value,
    });
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo exportar el reporte';
  } finally {
    exportando.value = false;
  }
}

// El detector avisa por WebSocket admin cuando encontró casos nuevos: se recarga la lista.
const { on } = useAdminNotifications();
on('cromo_inconsistencias_nuevas', (mensajeWs) => {
  const nuevos = Number(mensajeWs.nuevos ?? 0);
  mensaje.value = `El detector encontró ${nuevos} caso(s) nuevo(s).`;
  void reloadFromZero();
});

// Una evaluación del árbitro puede haber corregido casos: la pestaña Casos se recarga igual.
on('arbitro_cromo_evaluado', () => {
  void reloadFromZero();
});

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
  seleccion.value = todosSeleccionados.value ? new Set() : new Set(editablesVisibles.value.map((i) => i.id));
}

async function aplicar(ids: number[], estado: EstadoDestinoInconsistencia): Promise<void> {
  if (!ids.length) return;
  const accion = ACCIONES[estado];
  if (accion.confirmar && !window.confirm(accion.confirmar.replace('{n}', String(ids.length)))) return;
  accionando.value = true;
  error.value = '';
  mensaje.value = '';
  rechazados.value = [];
  try {
    const resultado = await cambiarEstadoInconsistencias(ids, estado);
    mensaje.value = `${resultado.aplicados.length} caso(s) ${accion.verbo}.`;
    rechazados.value = resultado.rechazados;
    await reloadFromZero();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : `No se pudo completar: ${accion.verbo}`;
  } finally {
    accionando.value = false;
  }
}

function aplicarSeleccion(estado: EstadoDestinoInconsistencia): void {
  void aplicar([...seleccion.value], estado);
}

// ── Detección manual: progreso por el SSE de corridas ─────────────────────

const sse = useCorridaSse({
  recargarEstado: cargarDeteccion,
  onInicio: (data) => {
    if (deteccion.value && typeof data.total_objetivo === 'number') deteccion.value.total_objetivo = data.total_objetivo;
  },
  onPagina: (data) => {
    if (!deteccion.value) return;
    if (typeof data.leidas === 'number') deteccion.value.leidas = data.leidas;
    if (typeof data.total === 'number') deteccion.value.total_objetivo = data.total;
    faseActual.value = typeof data.paso === 'string' ? data.paso : faseActual.value;
  },
  onResumen: (data) => {
    if (deteccion.value && typeof data.estado === 'string') deteccion.value.estado = data.estado;
    faseActual.value = '';
    void reloadFromZero();
  },
  onErrorNegocio: (detalle) => {
    erroresDeteccion.value = [detalle, ...erroresDeteccion.value].slice(0, 10);
  },
});

async function cargarDeteccion(): Promise<void> {
  try {
    const estado = await obtenerDeteccion();
    deteccion.value = estado.corrida;
    if (estado.corrida?.estado === 'EN_CURSO') sse.conectar(estado.corrida.id);
  } catch {
    // El estado de la detección es accesorio: el listado funciona igual.
  }
}

async function lanzarDeteccionManual(): Promise<void> {
  const ok = window.confirm(
    'La detección revisa todo el inventario y confirma en Cromo los cables candidatos a cuarentena automática. ¿Lanzarla?',
  );
  if (!ok) return;
  lanzando.value = true;
  error.value = '';
  erroresDeteccion.value = [];
  try {
    const { corrida_id } = await lanzarDeteccion();
    deteccion.value = {
      id: corrida_id,
      estado: 'EN_CURSO',
      total_objetivo: null,
      leidas: 0,
      errores: 0,
      iniciada_at: null,
      finalizada_at: null,
    };
    sse.conectar(corrida_id);
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo lanzar la detección';
  } finally {
    lanzando.value = false;
  }
}

onMounted(async () => {
  await Promise.all([reloadFromZero(), cargarDeteccion(), cargarAviso()]);
});

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
});
</script>

<style scoped>
.inconsistencias-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.inconsistencias-viewer__tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--color-divider);
}

.inconsistencias-viewer__tab {
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  color: color-mix(in srgb, var(--color-text) 66%, transparent);
}

.inconsistencias-viewer__tab:hover { color: var(--color-text); }

.inconsistencias-viewer__tab.is-active {
  border-bottom-color: var(--color-accent);
  color: var(--color-accent-200);
}

.inconsistencias-viewer__aviso {
  margin-bottom: 10px;
  font-size: 13px;
  color: var(--color-neutral-500);
}

.inconsistencias-viewer__aviso-form {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
  padding-top: 8px;
}

.inconsistencias-viewer__aviso-form label {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
}

.inconsistencias-viewer__aviso-form input[type='text'] {
  min-height: 34px;
  width: 320px;
  padding: 5px 10px;
  font-size: 13px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.inconsistencias-viewer__aviso-form .inconsistencias-viewer__aviso-check {
  flex-direction: row;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.inconsistencias-viewer__toolbar {
  padding: 4px 0 14px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.inconsistencias-viewer__toolbar-row {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.inconsistencias-viewer__servicio,
.inconsistencias-viewer__localidad {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
  color: var(--color-neutral-500);
}

.inconsistencias-viewer__servicio input {
  min-height: 34px;
  width: 160px;
  padding: 5px 10px;
  font-size: 13px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.inconsistencias-viewer__chips {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  flex: 1;
}

.inconsistencias-viewer__chips-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-neutral-500);
  margin-right: 2px;
}

.inconsistencias-viewer__chip {
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

.inconsistencias-viewer__chip:hover { border-color: var(--color-accent); }

.inconsistencias-viewer__chip.is-active {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}

.inconsistencias-viewer__chip-count {
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.inconsistencias-viewer__count {
  margin-left: auto;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
  white-space: nowrap;
}

.inconsistencias-viewer__count strong { color: var(--color-text); font-weight: 500; }

.inconsistencias-viewer__separador {
  width: 1px;
  height: 22px;
  margin: 0 6px;
  background: var(--color-divider);
}

.inconsistencias-viewer__errores-deteccion {
  flex-basis: 100%;
  margin: 0;
  padding-left: 18px;
  font-size: 11.5px;
  color: var(--color-state-error);
}

.inconsistencias-viewer__deteccion {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.inconsistencias-viewer__inline-error,
.inconsistencias-viewer__inline-ok {
  margin-bottom: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 12.5px;
}

.inconsistencias-viewer__inline-error {
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
}

.inconsistencias-viewer__inline-ok {
  background: color-mix(in srgb, var(--color-state-ok) 14%, transparent);
  color: var(--color-state-ok);
}

.inconsistencias-viewer__rechazados {
  margin: 0 0 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  font-size: 12.5px;
  background: color-mix(in srgb, var(--color-state-warn) 14%, transparent);
  color: var(--color-state-warn);
}

.inconsistencias-viewer__rechazados ul { margin: 6px 0 8px; padding-left: 18px; }

.inconsistencias-viewer__scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.inconsistencias-viewer__tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.inconsistencias-viewer__tabla th {
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

.inconsistencias-viewer__tabla td {
  padding: 8px 10px;
  vertical-align: top;
  border-bottom: 1px solid var(--color-neutral-800);
  color: var(--color-text);
}

.inconsistencias-viewer__check { width: 28px; }

.inconsistencias-viewer__sub {
  display: block;
  font-size: 11px;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.inconsistencias-viewer__link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-accent-200);
  cursor: pointer;
  font: inherit;
}

.inconsistencias-viewer__link:hover { text-decoration: underline; }

.inconsistencias-viewer__tipo {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-pill);
  font-size: 11.5px;
  background: color-mix(in srgb, var(--color-state-idle) 16%, transparent);
  color: var(--color-text);
}

.inconsistencias-viewer__revision.is-manual { color: var(--color-state-warn); }
.inconsistencias-viewer__revision.is-auto { color: var(--color-state-idle); }


.inconsistencias-viewer__evidencia {
  max-width: 360px;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.inconsistencias-viewer__estado { font-size: 11.5px; font-weight: 500; }
.inconsistencias-viewer__estado.is-pendiente { color: var(--color-state-warn); }
.inconsistencias-viewer__estado.is-cuarentena { color: var(--color-state-error); }
.inconsistencias-viewer__estado.is-reportada { color: var(--color-accent-200); }
.inconsistencias-viewer__estado.is-corregida { color: var(--color-state-ok); }
.inconsistencias-viewer__estado.is-aceptada { color: var(--color-state-idle); }

.inconsistencias-viewer__acciones-fila {
  white-space: nowrap;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.inconsistencias-viewer__localidad input {
  min-height: 34px;
  width: 160px;
  padding: 5px 10px;
  font-size: 13px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.inconsistencias-viewer__state-box {
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

.inconsistencias-viewer__state-box i { font-size: 26px; color: var(--color-neutral-600); margin-bottom: 4px; }
.inconsistencias-viewer__state-box h3 { font-size: 15px; font-weight: 500; margin: 0; }
.inconsistencias-viewer__state-box p {
  font-size: 12.5px;
  line-height: 1.5;
  margin: 0;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.inconsistencias-viewer__loading-more,
.inconsistencias-viewer__mas {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 14px 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.inconsistencias-viewer__spin { font-size: 14px; animation: spin 1s linear infinite; }

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
