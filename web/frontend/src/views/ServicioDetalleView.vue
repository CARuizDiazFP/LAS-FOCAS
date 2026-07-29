<!--
  Nombre de archivo: ServicioDetalleView.vue
  Ubicación de archivo: web/frontend/src/views/ServicioDetalleView.vue
  Descripción: Vista de detalle de servicio con cabecera técnica e interior dashboard de tarjetas operativas
-->
<template>
  <section class="servicio-detalle">
    <header class="servicio-detalle__header">
      <div>
        <p class="servicio-detalle__kicker">Servicio · ID origen {{ servicio?.numero_primer_servicio || '---' }}</p>
        <h1>{{ servicio?.nombre_cliente || 'Cliente sin dato' }}</h1>
        <p class="servicio-detalle__subline">{{ domicilio }}</p>
      </div>

      <div class="servicio-detalle__badges">
        <span class="badge">Estado: {{ servicio?.estado_servicio || 'DESCONOCIDO' }}</span>
        <span class="badge">Tipo: {{ servicio?.tipo_servicio || 'Sin dato' }}</span>
        <span class="badge">SLA: {{ servicio?.sla_prometido || 'Sin dato' }}</span>
      </div>
    </header>

    <section class="servicio-detalle__history" aria-label="Histórico de IDs">
      <strong>Histórico de IDs</strong>
      <div class="servicio-detalle__history-track">
        <span v-for="(id, index) in historicoIds" :key="`${id}-${index}`" class="history-node">
          {{ id }}
        </span>
      </div>
    </section>

    <p v-if="error" class="servicio-detalle__error">{{ error }}</p>
    <p v-if="loading" class="servicio-detalle__loading">Cargando detalle del servicio...</p>

    <section v-if="servicio" class="servicio-detalle__dashboard">
      <article class="dash-card" role="button" tabindex="0">
        <header>
          <h2>RECLAMOS</h2>
          <small>SLA + Repetitividad</small>
        </header>

        <p class="dash-line">
          Reclamos asociados en servicio: <strong>{{ reclamosCount }}</strong>
        </p>
        <p class="dash-line" v-if="reportesLoading">Cargando histórico de informes...</p>
        <p class="dash-line error" v-else-if="reportesError">{{ reportesError }}</p>
        <p class="dash-line" v-else>
          SLA: <strong>{{ resumenSla }}</strong>
        </p>
        <p class="dash-line" v-if="!reportesLoading && !reportesError">
          Repetitividad: <strong>{{ resumenRepetitividad }}</strong>
        </p>

        <div class="dash-actions">
          <RouterLink class="chip-link" to="/sla">Abrir SLA</RouterLink>
          <RouterLink class="chip-link" to="/repetitividad">Abrir Repetitividad</RouterLink>
          <RouterLink class="chip-link" to="/reports-history">Historial</RouterLink>
        </div>
      </article>

      <article class="dash-card" role="button" tabindex="0">
        <header>
          <h2>FO</h2>
          <small>Camino de fibra óptica</small>
        </header>

        <p class="dash-line" v-if="foLoading">Cargando rutas FO del servicio...</p>
        <p class="dash-line error" v-else-if="foError">{{ foError }}</p>
        <template v-else>
          <p class="dash-line">
            Rutas detectadas: <strong>{{ foRutas.length }}</strong>
          </p>
          <p class="dash-line" v-if="rutaPrincipal">
            Ruta principal: <strong>{{ rutaPrincipal.nombre }}</strong> ({{ rutaPrincipal.tipo }})
          </p>
          <p class="dash-line" v-if="foTrackingResumen">
            Topología: <strong>{{ foTrackingResumen.camaras }}</strong> cámaras ·
            <strong>{{ foTrackingResumen.cables }}</strong> cables
          </p>
          <p class="dash-line" v-if="foTrackingResumen?.puntaA || foTrackingResumen?.puntaB">
            Puntas: {{ foTrackingResumen?.puntaA || 'N/D' }} -> {{ foTrackingResumen?.puntaB || 'N/D' }}
          </p>
        </template>

        <div class="dash-actions">
          <RouterLink class="chip-link" to="/infra">Ir a Infra FO</RouterLink>
        </div>
      </article>

      <article class="dash-card" role="button" tabindex="0">
        <header>
          <h2>Ingresos</h2>
          <small>Registro de intervención</small>
        </header>
        <p>
          Contenedor preparado para registrar ingresos a cámaras por las que tributa
          el servicio con trazabilidad operativa.
        </p>
      </article>

      <article class="dash-card" role="button" tabindex="0">
        <header>
          <h2>Análisis de mejora</h2>
          <small>Asistencia LLM</small>
        </header>
        <p class="dash-line">
          Contexto listo para análisis: cliente, estado, SLA, histórico de IDs y resumen FO.
        </p>
        <p class="dash-line">
          Próximo paso: integrar endpoint de recomendación con prompt técnico y trazabilidad.
        </p>
      </article>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { getServicioDetail, type ServicioItem } from '../api/servicios';

const route = useRoute();
const router = useRouter();

const servicio = ref<ServicioItem | null>(null);
const loading = ref(false);
const error = ref('');

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

const reportesLoading = ref(false);
const reportesError = ref('');
const reporteSla = ref<ReportHistoryItem | null>(null);
const reporteRepetitividad = ref<ReportHistoryItem | null>(null);

const idParam = computed(() => String(route.params.idServicio ?? '').trim());

const historicoIds = computed(() => {
  if (!servicio.value) return [] as string[];

  const ids = [servicio.value.numero_primer_servicio, servicio.value.numero_linea]
    .map((value) => (value ?? '').trim())
    .filter((value, index, arr) => value.length > 0 && arr.indexOf(value) === index);

  return ids.length > 0 ? ids : [idParam.value];
});

const reclamosCount = computed(() => servicio.value?.reclamos?.length ?? 0);

const rutaPrincipal = computed(() => {
  const rutas = foRutas.value;
  if (rutas.length === 0) return null;
  const activa = rutas.find((ruta) => ruta.activa);
  if (activa) return activa;
  const principal = rutas.find((ruta) => (ruta.tipo ?? '').toUpperCase() === 'PRINCIPAL');
  return principal ?? rutas[0];
});

const resumenSla = computed(() => formatReporteSummary(reporteSla.value));
const resumenRepetitividad = computed(() => formatReporteSummary(reporteRepetitividad.value));

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
  display: grid;
  gap: var(--space-4);
}

.servicio-detalle__header {
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
  background: linear-gradient(155deg, rgba(8, 18, 34, 0.92), rgba(17, 37, 66, 0.88));
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-3);
}

.servicio-detalle__kicker {
  margin: 0 0 var(--space-1);
  color: var(--color-text-muted);
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.servicio-detalle__header h1 {
  margin: 0;
  font-size: 1.25rem;
}

.servicio-detalle__subline {
  margin: var(--space-2) 0 0;
  color: var(--color-text-muted);
}

.servicio-detalle__badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  align-content: flex-start;
  gap: var(--space-2);
}

.badge {
  border: 1px solid rgba(96, 165, 250, 0.45);
  background: rgba(59, 130, 246, 0.16);
  border-radius: var(--radius-pill);
  padding: 4px 10px;
  font-size: 0.76rem;
  color: #dbeafe;
}

.servicio-detalle__history {
  border: 1px dashed var(--color-border-default);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  display: grid;
  gap: var(--space-2);
}

.servicio-detalle__history-track {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.history-node {
  border: 1px solid rgba(96, 165, 250, 0.42);
  border-radius: var(--radius-pill);
  padding: 4px 10px;
  font-size: 0.82rem;
  color: #bfdbfe;
  background: rgba(30, 58, 96, 0.35);
}

.history-node:not(:last-child)::after {
  content: '->';
  margin-left: 10px;
  color: var(--color-text-muted);
}

.servicio-detalle__error {
  margin: 0;
  color: #fca5a5;
}

.servicio-detalle__loading {
  margin: 0;
  color: var(--color-text-muted);
}

.servicio-detalle__dashboard {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.dash-card {
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-lg);
  padding: var(--space-3);
  background: linear-gradient(165deg, rgba(12, 20, 34, 0.95), rgba(19, 32, 54, 0.9));
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.28);
  min-height: 170px;
}

.dash-card header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.dash-card h2 {
  margin: 0;
  font-size: 1rem;
}

.dash-card small {
  color: var(--color-text-muted);
}

.dash-card p {
  margin: 0;
  color: var(--color-text-secondary, #cbd5e1);
  line-height: 1.45;
}

.dash-line {
  margin: 0;
  font-size: 0.88rem;
}

.dash-line.error {
  color: #fca5a5;
}

.dash-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.chip-link {
  text-decoration: none;
  border: 1px solid rgba(96, 165, 250, 0.48);
  border-radius: var(--radius-pill);
  padding: 4px 10px;
  font-size: 0.78rem;
  color: #bfdbfe;
  background: rgba(37, 99, 235, 0.15);
}

.chip-link:hover {
  background: rgba(37, 99, 235, 0.28);
}

@media (max-width: 960px) {
  .servicio-detalle__header {
    grid-template-columns: 1fr;
  }

  .servicio-detalle__badges {
    justify-content: flex-start;
  }

  .servicio-detalle__dashboard {
    grid-template-columns: 1fr;
  }
}
</style>
