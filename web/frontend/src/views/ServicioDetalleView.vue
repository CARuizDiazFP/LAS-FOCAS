<!--
  Nombre de archivo: ServicioDetalleView.vue
  Ubicación de archivo: web/frontend/src/views/ServicioDetalleView.vue
  Descripción: Vista de detalle de servicio — cabecera, histórico de IDs, tira de métricas y paneles operativos
-->
<template>
  <section class="servicio-detalle">
    <nav class="servicio-detalle__migas" aria-label="Ruta de navegación">
      <RouterLink to="/servicios">Servicios</RouterLink>
      <i class="ph ph-caret-right" aria-hidden="true"></i>
      <span class="servicio-detalle__migas-actual">{{ idParam || '—' }}</span>
    </nav>

    <header class="servicio-detalle__header">
      <div class="servicio-detalle__identity">
        <span class="servicio-detalle__kicker">Servicio · ID origen {{ servicio?.numero_primer_servicio || '---' }}</span>
        <h1 :class="{ 'is-baja': estadoToken === 'error' }">{{ servicio?.nombre_cliente || 'Cliente sin dato' }}</h1>
        <p class="servicio-detalle__domicilio">{{ domicilio }}</p>
      </div>

      <div class="servicio-detalle__side">
        <div class="servicio-detalle__estado-row">
          <span :class="['servicio-detalle__estado-dot', `is-${estadoToken}`]" aria-hidden="true"></span>
          <span class="servicio-detalle__estado-text">{{ servicio?.estado_servicio || 'Desconocido' }}</span>
          <span class="servicio-detalle__separator" aria-hidden="true"></span>
          <span class="servicio-detalle__chip">{{ (servicio?.tipo_servicio || 'Sin dato').toUpperCase() }}</span>
          <span v-if="servicio?.sla_prometido" class="servicio-detalle__chip is-outline">SLA {{ servicio.sla_prometido }}</span>
          <span class="servicio-detalle__separator" aria-hidden="true"></span>
          <select
            v-if="isAdmin && servicio"
            class="servicio-detalle__categoria-select"
            :value="servicio.categoria"
            :disabled="guardandoCategoria"
            @change="onCambiarCategoria(Number(($event.target as HTMLSelectElement).value))"
          >
            <option v-for="categoria in CATEGORIAS_SERVICIO" :key="categoria" :value="categoria">
              {{ categoriaLabel(categoria) }}
            </option>
          </select>
          <span v-else-if="servicio" class="servicio-detalle__chip is-outline">{{ categoriaLabel(servicio.categoria) }}</span>
          <select
            v-if="isAdmin && servicio"
            class="servicio-detalle__verificable-select"
            :value="String(servicio.es_verificable)"
            :disabled="guardandoVerificable"
            @change="onCambiarVerificable(($event.target as HTMLSelectElement).value === 'true')"
          >
            <option value="true">Verificable</option>
            <option value="false">No verificable</option>
          </select>
          <span v-else-if="servicio && !servicio.es_verificable" class="servicio-detalle__chip is-warning">No verificable</span>
        </div>
        <p v-if="errorCategoria" class="servicio-detalle__categoria-error">{{ errorCategoria }}</p>
        <p v-if="errorVerificable" class="servicio-detalle__categoria-error">{{ errorVerificable }}</p>

        <div class="servicio-detalle__actions">
          <button class="btn subtle" type="button" disabled title="Próximamente">
            <i class="ph ph-file-arrow-down" aria-hidden="true"></i>
            Exportar
          </button>
          <RouterLink class="btn primary" to="/infra">
            <i class="ph ph-tree-structure" aria-hidden="true"></i>
            Ver camino FO
          </RouterLink>
        </div>
      </div>
    </header>

    <hr class="noc-rule" />

    <section class="servicio-detalle__historico" aria-label="Histórico de IDs">
      <span class="servicio-detalle__historico-label">Histórico de IDs</span>
      <div class="servicio-detalle__historico-track">
        <template v-for="(id, index) in historicoIds" :key="`${id}-${index}`">
          <span :class="['servicio-detalle__nodo', { 'is-current': index === historicoIds.length - 1 }]">{{ id }}</span>
          <i v-if="index < historicoIds.length - 1" class="ph ph-arrow-right" aria-hidden="true"></i>
        </template>
      </div>
    </section>

    <p v-if="error" class="servicio-detalle__error">{{ error }}</p>
    <p v-if="loading" class="servicio-detalle__loading">Cargando detalle del servicio...</p>

    <template v-if="servicio">
      <section class="servicio-detalle__metrics" aria-label="Métricas del servicio">
        <div class="servicio-detalle__metric">
          <span class="servicio-detalle__metric-label">Reclamos 12m</span>
          <strong class="servicio-detalle__metric-value">{{ reclamosCount }}</strong>
          <span class="servicio-detalle__metric-note">—</span>
        </div>
        <div class="servicio-detalle__metric">
          <span class="servicio-detalle__metric-label">SLA</span>
          <strong class="servicio-detalle__metric-value">{{ reportesLoading ? '—' : slaEstadoCorto }}</strong>
          <span class="servicio-detalle__metric-note">prometido {{ servicio.sla_prometido || '—' }}</span>
        </div>
        <div class="servicio-detalle__metric">
          <span class="servicio-detalle__metric-label">Rutas FO</span>
          <strong class="servicio-detalle__metric-value">{{ foLoading ? '—' : foRutas.length }}</strong>
          <span class="servicio-detalle__metric-note">principal + backup</span>
        </div>
        <div class="servicio-detalle__metric">
          <span class="servicio-detalle__metric-label">Cámaras</span>
          <strong class="servicio-detalle__metric-value">{{ foLoading ? '—' : (foTrackingResumen?.camaras ?? '—') }}</strong>
          <span class="servicio-detalle__metric-note">{{ foTrackingResumen?.cables ?? 0 }} cables tributando</span>
        </div>
      </section>

      <section class="servicio-detalle__panels">
        <article class="servicio-detalle__panel">
          <header>
            <i class="ph ph-warning-octagon" aria-hidden="true"></i>
            <h2>Reclamos</h2>
            <small>SLA + Repetitividad</small>
          </header>
          <div class="servicio-detalle__hairline"></div>

          <p class="servicio-detalle__kv">
            <span>Reclamos asociados</span>
            <span>{{ reclamosCount }}</span>
          </p>
          <p v-if="reportesLoading" class="servicio-detalle__kv"><span>Informes</span><span>Cargando...</span></p>
          <p v-else-if="reportesError" class="servicio-detalle__kv is-error"><span>Informes</span><span>{{ reportesError }}</span></p>
          <template v-else>
            <p class="servicio-detalle__kv"><span>SLA</span><span>{{ resumenSla }}</span></p>
            <p class="servicio-detalle__kv"><span>Repetitividad</span><span>{{ resumenRepetitividad }}</span></p>
          </template>

          <div class="servicio-detalle__panel-actions">
            <RouterLink class="servicio-detalle__panel-link" to="/sla">Abrir SLA</RouterLink>
            <RouterLink class="servicio-detalle__panel-link" to="/repetitividad">Abrir Repetitividad</RouterLink>
            <RouterLink class="servicio-detalle__panel-link" to="/reports-history">Historial</RouterLink>
          </div>
        </article>

        <article class="servicio-detalle__panel">
          <header>
            <i class="ph ph-tree-structure" aria-hidden="true"></i>
            <h2>Camino FO</h2>
            <small>Infraestructura</small>
          </header>
          <div class="servicio-detalle__hairline"></div>

          <p v-if="foLoading" class="servicio-detalle__kv"><span>Rutas FO</span><span>Cargando...</span></p>
          <p v-else-if="foError" class="servicio-detalle__kv is-error"><span>Rutas FO</span><span>{{ foError }}</span></p>
          <template v-else>
            <p class="servicio-detalle__kv"><span>Rutas detectadas</span><span>{{ foRutas.length }}</span></p>
            <p v-if="rutaPrincipal" class="servicio-detalle__kv">
              <span>Ruta principal</span><span>{{ rutaPrincipal.nombre }} ({{ rutaPrincipal.tipo }})</span>
            </p>
            <p v-if="foTrackingResumen" class="servicio-detalle__kv">
              <span>Topología</span><span>{{ foTrackingResumen.camaras }} cámaras · {{ foTrackingResumen.cables }} cables</span>
            </p>
            <p v-if="foTrackingResumen?.puntaA || foTrackingResumen?.puntaB" class="servicio-detalle__kv">
              <span>Puntas</span><span>{{ foTrackingResumen?.puntaA || 'N/D' }} → {{ foTrackingResumen?.puntaB || 'N/D' }}</span>
            </p>
          </template>

          <p v-if="odfsLoading" class="servicio-detalle__kv"><span>ODFs asociadas</span><span>Cargando...</span></p>
          <p v-else-if="odfsError" class="servicio-detalle__kv is-error"><span>ODFs asociadas</span><span>{{ odfsError }}</span></p>
          <p v-else class="servicio-detalle__kv"><span>ODFs asociadas</span><span>{{ totalOdfs }}</span></p>

          <div class="servicio-detalle__panel-actions">
            <RouterLink class="servicio-detalle__panel-link" to="/infra">Ir a Infra FO</RouterLink>
            <RouterLink class="servicio-detalle__panel-link" to="/infra">Ver tracking</RouterLink>
          </div>
        </article>

        <article class="servicio-detalle__panel">
          <header>
            <i class="ph ph-sign-in" aria-hidden="true"></i>
            <h2>Ingresos</h2>
            <small>Trazabilidad</small>
          </header>
          <div class="servicio-detalle__hairline"></div>

          <p v-if="ingresosLoading" class="servicio-detalle__kv"><span>Ingresos</span><span>Cargando...</span></p>
          <p v-else-if="ingresosError" class="servicio-detalle__kv is-error"><span>Ingresos</span><span>{{ ingresosError }}</span></p>
          <p v-else-if="ingresos.length === 0" class="servicio-detalle__kv-text">
            Sin ingresos registrados para este servicio.
          </p>
          <template v-else>
            <p v-for="ingreso in ingresos" :key="ingreso.id" class="servicio-detalle__kv">
              <span>{{ ingreso.camara_nombre || `Cámara ${ingreso.camara_id}` }}</span>
              <span>{{ formatRangoIngreso(ingreso) }} · {{ ingreso.tecnico_id || 'Técnico sin identificar' }}</span>
            </p>
          </template>

          <div class="servicio-detalle__panel-actions">
            <button class="servicio-detalle__panel-link" type="button" disabled title="Próximamente">Registrar ingreso</button>
          </div>
        </article>

        <article class="servicio-detalle__panel">
          <header>
            <i class="ph ph-sparkle" aria-hidden="true"></i>
            <h2>Análisis de mejora</h2>
            <small>Asistencia LLM</small>
          </header>
          <div class="servicio-detalle__hairline"></div>
          <p class="servicio-detalle__kv-text">
            Contexto listo para análisis: cliente, estado, SLA, histórico de IDs y resumen FO.
          </p>

          <div class="servicio-detalle__panel-actions">
            <button class="servicio-detalle__panel-link" type="button" disabled title="Próximamente">Generar análisis</button>
          </div>
        </article>
      </section>

      <section class="servicio-detalle__odfs" aria-label="ODFs asociadas">
        <header class="servicio-detalle__odfs-header">
          <h2>ODFs asociadas</h2>
          <div class="servicio-detalle__odfs-header-right">
            <label class="servicio-detalle__odfs-toggle">
              <input v-model="showAllEmpalmes" type="checkbox" />
              Mostrar todos los empalmes (incl. no-ODF)
            </label>
            <span class="servicio-detalle__chip">{{ totalOdfs }} ODF(s)</span>
          </div>
        </header>

        <p v-if="odfsLoading" class="servicio-detalle__loading">Cargando ODFs asociadas...</p>
        <p v-else-if="odfsError" class="servicio-detalle__error">{{ odfsError }}</p>
        <p v-else-if="odfsFlat.length === 0" class="servicio-detalle__kv-text">
          Sin ODFs detectadas en el tracking de este servicio.
        </p>

        <template v-else>
          <div v-for="grupo in odfsPorRuta" :key="grupo.ruta_id" class="servicio-detalle__odfs-grupo">
            <h3 class="servicio-detalle__odfs-subtitulo">{{ grupo.ruta_nombre }} ({{ grupo.ruta_tipo }})</h3>
            <p v-if="grupo.terminal_a && grupo.terminal_b" class="servicio-detalle__odfs-puntas">
              Puntas ODF: {{ grupo.terminal_a.odf_id }}:{{ grupo.terminal_a.conector }} →
              {{ grupo.terminal_b.odf_id }}:{{ grupo.terminal_b.conector }}
            </p>

            <table class="tabla-odfs">
              <thead>
                <tr>
                  <th>Empalme ID</th>
                  <th>Descripción</th>
                  <th>Tipo</th>
                  <th>Cámara</th>
                  <th>Estado</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="fila in grupo.filas" :key="fila.empalme_id">
                  <td>{{ fila.empalme_id }}</td>
                  <td>{{ fila.descripcion }}</td>
                  <td>
                    <span :class="['servicio-detalle__chip', { 'is-outline': fila.es_transito }]">
                      {{ fila.es_transito ? 'ODF' : 'Empalme' }}
                    </span>
                  </td>
                  <td>
                    <span v-if="fila.camara_nombre">{{ fila.camara_nombre }}</span>
                    <span v-else class="servicio-detalle__odfs-muted">Sin match</span>
                  </td>
                  <td>
                    <span v-if="fila.camara_estado" class="servicio-detalle__odfs-estado">
                      <span
                        :class="['servicio-detalle__odfs-dot', `is-${estadoCamaraToken(fila.camara_estado)}`]"
                        aria-hidden="true"
                      ></span>
                      {{ fila.camara_estado }}
                    </span>
                    <span v-else class="servicio-detalle__odfs-muted">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { estadoCamaraToken } from '../api/camaras';
import {
  CATEGORIAS_SERVICIO,
  categoriaLabel,
  estadoServicioToken,
  getServicioDetail,
  updateServicioCategoria,
  updateServicioVerificable,
  type ServicioItem,
} from '../api/servicios';
import { useSession } from '../composables/useSession';

const route = useRoute();
const router = useRouter();
const { state } = useSession();
const isAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');

const servicio = ref<ServicioItem | null>(null);
const loading = ref(false);
const error = ref('');
const guardandoCategoria = ref(false);
const errorCategoria = ref('');
const guardandoVerificable = ref(false);
const errorVerificable = ref('');

interface InfraRutaItem {
  id: number;
  nombre: string;
  tipo: string;
  empalmes_count: number;
  activa: boolean;
}

interface InfraRutasResponse {
  status: string;
  rutas: InfraRutaItem[];
}

interface TrackingEntry {
  tipo: string;
}

interface InfraTrackingResponse {
  status: string;
  tracking: TrackingEntry[];
  punta_a?: { sitio?: string | null; identificador?: string | null; conector?: string | null } | null;
  punta_b?: { sitio?: string | null; identificador?: string | null; conector?: string | null } | null;
}

// ODFs asociadas (fuente: archivo de tracking de la ruta, no Cromo — ver Task 7/8 del plan
// "snappy-petting-music"). `empalme_id` siempre viene como string (regex del parser); `camara_*`
// son null cuando no hay match en app.empalmes; `ruta_tipo` nunca llega null desde el backend
// (default "PRINCIPAL" ya resuelto server-side).
interface InfraOdfTerminal {
  odf_id: string;
  conector: string;
}

interface InfraOdfEmpalme {
  empalme_id: string;
  descripcion: string;
  es_transito: boolean;
  camara_id: number | null;
  camara_nombre: string | null;
  camara_estado: string | null;
}

interface InfraOdfRuta {
  ruta_id: number;
  ruta_nombre: string;
  ruta_tipo: string;
  activa: boolean;
  sin_tracking: boolean;
  terminal_a: InfraOdfTerminal | null;
  terminal_b: InfraOdfTerminal | null;
  transitos_count: number;
  empalmes_count: number;
  empalmes: InfraOdfEmpalme[];
}

interface InfraOdfsResponse {
  status: string;
  servicio_id: string;
  total_odfs: number;
  total_empalmes: number;
  rutas: InfraOdfRuta[];
}

// Ingresos técnicos (Slack) a las cámaras que atraviesa el servicio. `tecnico_id` es un id crudo
// de usuario de Slack (p. ej. "U0AUB6CRE4A"), no un nombre resuelto — se muestra tal cual.
interface InfraServicioIngreso {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
  camara_id: number;
  camara_nombre: string | null;
}

interface InfraServicioIngresosResponse {
  status: string;
  servicio_id: string;
  total: number;
  ingresos: InfraServicioIngreso[];
}

interface ReportHistoryItem {
  id: number;
  status: string;
  started_at: string | null;
  report_type: string;
}

interface ReportsHistoryResponse {
  items?: ReportHistoryItem[];
}

const foLoading = ref(false);
const foError = ref('');
const foRutas = ref<InfraRutaItem[]>([]);
const foTrackingResumen = ref<{
  camaras: number;
  cables: number;
  puntaA: string | null;
  puntaB: string | null;
} | null>(null);

const odfsLoading = ref(false);
const odfsError = ref('');
const odfsRutas = ref<InfraOdfRuta[]>([]);
const totalOdfs = ref(0);
// Por defecto sólo se ven los empalmes que son ODF (es_transito === true); tildar el checkbox
// revela también los empalmes simples (cámaras de paso, etc.) del tracking.
const showAllEmpalmes = ref(false);

const ingresosLoading = ref(false);
const ingresosError = ref('');
const ingresos = ref<InfraServicioIngreso[]>([]);

const reportesLoading = ref(false);
const reportesError = ref('');
const reporteSla = ref<ReportHistoryItem | null>(null);
const reporteRepetitividad = ref<ReportHistoryItem | null>(null);

const idParam = computed(() => String(route.params.idServicio ?? '').trim());

const historicoIds = computed(() => {
  if (!servicio.value) return [] as string[];

  const alias = [...(servicio.value.alias_ids ?? [])].sort((a, b) => {
    const numA = Number(a);
    const numB = Number(b);
    if (Number.isFinite(numA) && Number.isFinite(numB)) return numA - numB;
    return a.localeCompare(b);
  });

  const ids = [servicio.value.numero_primer_servicio, ...alias, servicio.value.numero_linea]
    .map((value) => (value ?? '').trim())
    .filter((value, index, arr) => value.length > 0 && arr.indexOf(value) === index);

  return ids.length > 0 ? ids : [idParam.value];
});

const reclamosCount = computed(() => servicio.value?.reclamos?.length ?? 0);
const estadoToken = computed(() => estadoServicioToken(servicio.value?.estado_servicio));

const rutaPrincipal = computed(() => {
  const rutas = foRutas.value;
  if (rutas.length === 0) return null;
  const activa = rutas.find((ruta) => ruta.activa);
  if (activa) return activa;
  const principal = rutas.find((ruta) => (ruta.tipo ?? '').toUpperCase() === 'PRINCIPAL');
  return principal ?? rutas[0];
});

// Fila individual aplanada de un empalme, etiquetada con los datos de su ruta padre — filtra a
// sólo es_transito === true salvo que showAllEmpalmes esté activo. terminal_a/terminal_b viven
// aparte, a nivel de ruta (ver odfsPorRuta) — nunca se cruzan contra una fila puntual acá.
interface OdfFlatRow extends InfraOdfEmpalme {
  ruta_id: number;
  ruta_nombre: string;
  ruta_tipo: string;
}

const odfsFlat = computed<OdfFlatRow[]>(() =>
  odfsRutas.value.flatMap((ruta) =>
    ruta.empalmes
      .filter((empalme) => empalme.es_transito || showAllEmpalmes.value)
      .map((empalme) => ({
        ...empalme,
        ruta_id: ruta.ruta_id,
        ruta_nombre: ruta.ruta_nombre,
        ruta_tipo: ruta.ruta_tipo,
      })),
  ),
);

// Reagrupa odfsFlat por ruta para el render (subtítulo + leyenda de puntas + tabla por ruta),
// omitiendo rutas sin ninguna fila visible bajo el filtro actual.
interface OdfGrupoRuta {
  ruta_id: number;
  ruta_nombre: string;
  ruta_tipo: string;
  terminal_a: InfraOdfTerminal | null;
  terminal_b: InfraOdfTerminal | null;
  filas: OdfFlatRow[];
}

const odfsPorRuta = computed<OdfGrupoRuta[]>(() =>
  odfsRutas.value
    .map((ruta) => ({
      ruta_id: ruta.ruta_id,
      ruta_nombre: ruta.ruta_nombre,
      ruta_tipo: ruta.ruta_tipo,
      terminal_a: ruta.terminal_a,
      terminal_b: ruta.terminal_b,
      filas: odfsFlat.value.filter((fila) => fila.ruta_id === ruta.ruta_id),
    }))
    .filter((grupo) => grupo.filas.length > 0),
);

const resumenSla = computed(() => formatReporteSummary(reporteSla.value));
const resumenRepetitividad = computed(() => formatReporteSummary(reporteRepetitividad.value));

const slaEstadoCorto = computed(() => {
  if (!reporteSla.value) return 'Sin informes';
  return reporteSla.value.status === 'success' ? 'Informe OK' : reporteSla.value.status;
});

const domicilio = computed(() => {
  if (!servicio.value) return 'Sin dato';
  const parts = [servicio.value.direccion, servicio.value.direccion_2, servicio.value.localidad, servicio.value.provincia]
    .map((value) => (value ?? '').trim())
    .filter((value) => value.length > 0);
  return parts.length > 0 ? parts.join(' · ') : 'Sin dato';
});

async function loadDetalle(): Promise<void> {
  const id = idParam.value;
  if (!id) {
    error.value = 'ID inválido';
    servicio.value = null;
    return;
  }

  loading.value = true;
  error.value = '';

  try {
    const response = await getServicioDetail(id);
    servicio.value = response.servicio;

    await Promise.all([
      loadFoResumen(response.id_origen),
      loadReportesResumen(),
      loadOdfsAsociadas(response.id_origen),
      loadIngresosAsociados(response.id_origen),
    ]);

    const idOrigen = response.id_origen.trim();
    if (idOrigen && idOrigen !== id) {
      await router.replace(`/servicios/ID/${encodeURIComponent(idOrigen)}`);
    }
  } catch (err: unknown) {
    servicio.value = null;
    error.value = err instanceof Error ? err.message : 'No se pudo cargar el detalle del servicio';
  } finally {
    loading.value = false;
  }
}

async function onCambiarCategoria(categoria: number): Promise<void> {
  if (!servicio.value || guardandoCategoria.value) return;
  const anterior = servicio.value.categoria;
  guardandoCategoria.value = true;
  errorCategoria.value = '';
  try {
    servicio.value = await updateServicioCategoria(servicio.value.id, categoria);
  } catch (err: unknown) {
    errorCategoria.value = err instanceof Error ? err.message : 'No se pudo cambiar el Nivel Cliente';
    if (servicio.value) servicio.value.categoria = anterior;
  } finally {
    guardandoCategoria.value = false;
  }
}

async function onCambiarVerificable(esVerificable: boolean): Promise<void> {
  if (!servicio.value || guardandoVerificable.value) return;
  const anterior = servicio.value.es_verificable;
  guardandoVerificable.value = true;
  errorVerificable.value = '';
  try {
    servicio.value = await updateServicioVerificable(servicio.value.id, esVerificable);
  } catch (err: unknown) {
    errorVerificable.value = err instanceof Error ? err.message : 'No se pudo cambiar la verificabilidad';
    if (servicio.value) servicio.value.es_verificable = anterior;
  } finally {
    guardandoVerificable.value = false;
  }
}

function formatPunta(
  punta?: { sitio?: string | null; identificador?: string | null; conector?: string | null } | null,
): string | null {
  if (!punta) return null;
  const sitio = (punta.sitio ?? '').trim();
  const identificador = (punta.identificador ?? '').trim();
  const conector = (punta.conector ?? '').trim();
  const texto = [sitio, identificador, conector].filter((part) => part.length > 0).join(':');
  return texto || null;
}

function formatReporteSummary(item: ReportHistoryItem | null): string {
  if (!item) return 'Sin ejecuciones recientes';
  const estado = item.status === 'success' ? 'correcto' : item.status;
  const fecha = item.started_at
    ? new Date(item.started_at).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' })
    : 'sin fecha';
  return `${estado} · ${fecha}`;
}

function formatFechaIngreso(value: string | null): string {
  if (!value) return 'Sin fecha';
  return new Date(value).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' });
}

function formatRangoIngreso(item: InfraServicioIngreso): string {
  const inicio = formatFechaIngreso(item.fecha_inicio);
  const fin = item.fecha_fin ? formatFechaIngreso(item.fecha_fin) : 'en curso';
  return `${inicio} → ${fin}`;
}

async function parseJsonOrError<T>(response: Response): Promise<T> {
  const data = await response.json() as T & { error?: string };
  if (!response.ok) {
    throw new Error(data.error ?? `Error ${response.status}`);
  }
  return data;
}

async function loadFoResumen(idOrigen: string): Promise<void> {
  const clean = idOrigen.trim();
  if (!clean) return;

  foLoading.value = true;
  foError.value = '';
  foRutas.value = [];
  foTrackingResumen.value = null;

  try {
    const rutasResponse = await fetch(`/api/infra/servicios/${encodeURIComponent(clean)}/rutas`, {
      credentials: 'include',
    });
    const rutasData = await parseJsonOrError<InfraRutasResponse>(rutasResponse);
    foRutas.value = rutasData.rutas ?? [];

    const principal = rutaPrincipal.value;
    if (!principal) return;

    const trackingResponse = await fetch(`/api/infra/rutas/${principal.id}/tracking`, {
      credentials: 'include',
    });
    const trackingData = await parseJsonOrError<InfraTrackingResponse>(trackingResponse);
    const entries = trackingData.tracking ?? [];

    foTrackingResumen.value = {
      camaras: entries.filter((entry) => (entry.tipo ?? '').toLowerCase() === 'camara').length,
      cables: entries.filter((entry) => (entry.tipo ?? '').toLowerCase() === 'cable').length,
      puntaA: formatPunta(trackingData.punta_a),
      puntaB: formatPunta(trackingData.punta_b),
    };
  } catch (err: unknown) {
    foError.value = err instanceof Error ? err.message : 'No se pudo cargar el resumen FO';
  } finally {
    foLoading.value = false;
  }
}

async function loadOdfsAsociadas(idOrigen: string): Promise<void> {
  const clean = idOrigen.trim();
  if (!clean) return;

  odfsLoading.value = true;
  odfsError.value = '';
  odfsRutas.value = [];
  totalOdfs.value = 0;

  try {
    const response = await fetch(`/api/infra/servicios/${encodeURIComponent(clean)}/odfs`, {
      credentials: 'include',
    });
    const data = await parseJsonOrError<InfraOdfsResponse>(response);
    odfsRutas.value = data.rutas ?? [];
    totalOdfs.value = data.total_odfs ?? 0;
  } catch (err: unknown) {
    odfsError.value = err instanceof Error ? err.message : 'No se pudo cargar ODFs asociadas';
  } finally {
    odfsLoading.value = false;
  }
}

async function loadIngresosAsociados(idOrigen: string): Promise<void> {
  const clean = idOrigen.trim();
  if (!clean) return;

  ingresosLoading.value = true;
  ingresosError.value = '';
  ingresos.value = [];

  try {
    const response = await fetch(`/api/infra/servicios/${encodeURIComponent(clean)}/ingresos`, {
      credentials: 'include',
    });
    const data = await parseJsonOrError<InfraServicioIngresosResponse>(response);
    ingresos.value = data.ingresos ?? [];
  } catch (err: unknown) {
    ingresosError.value = err instanceof Error ? err.message : 'No se pudo cargar ingresos asociados';
  } finally {
    ingresosLoading.value = false;
  }
}

async function loadReportesResumen(): Promise<void> {
  reportesLoading.value = true;
  reportesError.value = '';
  reporteSla.value = null;
  reporteRepetitividad.value = null;

  try {
    const [slaResponse, repResponse] = await Promise.all([
      fetch('/api/reports/history?type=sla&limit=1', { credentials: 'include' }),
      fetch('/api/reports/history?type=repetitividad&limit=1', { credentials: 'include' }),
    ]);

    const slaData = await parseJsonOrError<ReportsHistoryResponse>(slaResponse);
    const repData = await parseJsonOrError<ReportsHistoryResponse>(repResponse);

    reporteSla.value = (slaData.items ?? [])[0] ?? null;
    reporteRepetitividad.value = (repData.items ?? [])[0] ?? null;
  } catch (err: unknown) {
    reportesError.value = err instanceof Error ? err.message : 'No se pudo cargar historial de informes';
  } finally {
    reportesLoading.value = false;
  }
}

watch(
  () => idParam.value,
  () => {
    void loadDetalle();
  },
  { immediate: true },
);
</script>

<style scoped>
.servicio-detalle {
  padding-bottom: 26px;
}

.servicio-detalle__migas {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 16px 26px 0;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 48%, transparent);
}

.servicio-detalle__migas a {
  color: inherit;
}

.servicio-detalle__migas i {
  font-size: 11px;
}

.servicio-detalle__migas-actual {
  color: color-mix(in srgb, var(--color-text) 78%, transparent);
  font-variant-numeric: tabular-nums;
}

.servicio-detalle__header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 20px;
  padding: 14px 26px 18px;
}

.servicio-detalle__identity {
  min-width: 0;
}

.servicio-detalle__kicker {
  display: block;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.servicio-detalle__header h1 {
  margin: 6px 0 0;
  font-size: 34px;
  line-height: 1.1;
  text-wrap: pretty;
}

.servicio-detalle__header h1.is-baja {
  color: var(--color-state-error);
}

.servicio-detalle__verificable-select {
  padding: 3px 8px;
  font-size: 10.5px;
  border-radius: 6px;
  background: var(--color-surface);
  border: 1px solid var(--color-state-warn);
  color: var(--color-state-warn);
}

.servicio-detalle__chip.is-warning {
  background: transparent;
  border: 1px solid var(--color-state-warn);
  color: var(--color-state-warn);
}

.servicio-detalle__domicilio {
  margin: 8px 0 0;
  font-size: 13px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.servicio-detalle__side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 9px;
}

.servicio-detalle__estado-row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.servicio-detalle__estado-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-state-idle);
}
.servicio-detalle__estado-dot.is-ok { background: var(--color-state-ok); }
.servicio-detalle__estado-dot.is-warn { background: var(--color-state-warn); }
.servicio-detalle__estado-dot.is-error { background: var(--color-state-error); }

.servicio-detalle__estado-text {
  font-family: var(--font-heading);
  font-size: 13px;
  letter-spacing: 0.02em;
}

.servicio-detalle__separator {
  width: 1px;
  height: 13px;
  background: var(--color-divider);
}

.servicio-detalle__chip {
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 10.5px;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.servicio-detalle__chip.is-outline {
  background: transparent;
  border: 1px solid var(--color-accent);
  color: var(--color-accent);
}

.servicio-detalle__categoria-select {
  padding: 3px 8px;
  font-size: 10.5px;
  border-radius: 6px;
  background: var(--color-surface);
  border: 1px solid var(--color-accent);
  color: var(--color-accent);
}

.servicio-detalle__categoria-error {
  margin: -4px 0 0;
  text-align: right;
  font-size: 11.5px;
  color: var(--color-state-error);
}

.servicio-detalle__actions {
  display: flex;
  gap: 7px;
}

.servicio-detalle__actions .btn {
  min-height: 34px;
  font-size: 12.5px;
}

.servicio-detalle__historico {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 16px 26px;
}

.servicio-detalle__historico-label {
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-neutral-500);
}

.servicio-detalle__historico-track {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.servicio-detalle__historico-track i {
  font-size: 13px;
  color: var(--color-neutral-600);
}

.servicio-detalle__nodo {
  font-size: 12.5px;
  font-variant-numeric: tabular-nums;
  padding: 4px 11px;
  border-radius: 4px;
  background: var(--color-surface);
  color: color-mix(in srgb, var(--color-text) 68%, transparent);
}

.servicio-detalle__nodo.is-current {
  background: transparent;
  border: 1px solid var(--color-accent);
  color: var(--color-accent);
}

.servicio-detalle__error {
  margin: 0 26px;
  color: var(--color-state-error);
}

.servicio-detalle__loading {
  margin: 0 26px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.servicio-detalle__metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 11px;
  padding: 0 26px 16px;
}

.servicio-detalle__metric {
  padding: 11px 13px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.servicio-detalle__metric-label {
  display: block;
  font-size: 9.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-neutral-500);
}

.servicio-detalle__metric-value {
  display: block;
  margin-top: 4px;
  font-family: var(--font-heading);
  font-size: 24px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.servicio-detalle__metric-note {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.servicio-detalle__panels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
  padding: 0 26px 26px;
}

.servicio-detalle__panel {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 14px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
  min-height: 158px;
}

.servicio-detalle__panel header {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.servicio-detalle__panel header i {
  font-size: 16px;
  color: var(--color-accent);
  align-self: center;
}

.servicio-detalle__panel h2 {
  margin: 0;
  font-size: 15px;
}

.servicio-detalle__panel small {
  margin-left: auto;
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-neutral-500);
}

.servicio-detalle__hairline {
  height: 1px;
  background: var(--color-divider);
}

.servicio-detalle__kv {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 0;
  font-size: 12.5px;
}

.servicio-detalle__kv span:first-child {
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.servicio-detalle__kv span:last-child {
  margin-left: auto;
  text-align: right;
  color: var(--color-text);
}

.servicio-detalle__kv.is-error span:last-child {
  color: var(--color-state-error);
}

.servicio-detalle__kv-text {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.servicio-detalle__panel-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: auto;
  padding-top: 4px;
}

.servicio-detalle__panel-link {
  font-size: 11px;
  padding: 3px 9px;
  border: 1px solid var(--color-divider);
  border-radius: 4px;
  color: color-mix(in srgb, var(--color-text) 72%, transparent);
  text-decoration: none;
  background: transparent;
  cursor: pointer;
}

.servicio-detalle__panel-link:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.servicio-detalle__panel-link:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.servicio-detalle__odfs {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 0 26px 26px;
  padding: 16px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.servicio-detalle__odfs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.servicio-detalle__odfs-header h2 {
  margin: 0;
  font-size: 15px;
}

.servicio-detalle__odfs-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.servicio-detalle__odfs-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  cursor: pointer;
}

.servicio-detalle__odfs-grupo {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.servicio-detalle__odfs-grupo + .servicio-detalle__odfs-grupo {
  margin-top: 10px;
  padding-top: 12px;
  border-top: 1px solid var(--color-divider);
}

.servicio-detalle__odfs-subtitulo {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
}

.servicio-detalle__odfs-puntas {
  margin: 0;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.servicio-detalle__odfs-muted {
  color: color-mix(in srgb, var(--color-text) 40%, transparent);
}

.servicio-detalle__odfs-estado {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.servicio-detalle__odfs-dot {
  width: 7px;
  height: 7px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}
.servicio-detalle__odfs-dot.is-ok { background: var(--color-state-ok); }
.servicio-detalle__odfs-dot.is-warn { background: var(--color-state-warn); }
.servicio-detalle__odfs-dot.is-error { background: var(--color-state-error); }
.servicio-detalle__odfs-dot.is-idle { background: var(--color-state-idle); }

.tabla-odfs {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.tabla-odfs th,
.tabla-odfs td {
  text-align: left;
  padding: 6px 9px;
  border-bottom: 1px solid var(--color-divider);
}

.tabla-odfs th {
  font-weight: 500;
  font-size: 11px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

@media (max-width: 960px) {
  .servicio-detalle__header {
    grid-template-columns: 1fr;
  }

  .servicio-detalle__side {
    align-items: flex-start;
  }

  .servicio-detalle__metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .servicio-detalle__panels {
    grid-template-columns: 1fr;
  }
}
</style>
