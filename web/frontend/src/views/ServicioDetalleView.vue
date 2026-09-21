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

    <p v-if="error" class="servicio-detalle__error">{{ error }}</p>
    <p v-if="loading" class="servicio-detalle__loading">Cargando detalle del servicio...</p>

    <template v-if="servicio">
      <!-- Equipos y métricas se quedan en la ficha: son la identidad operativa del Servicio y
           entran en una línea cada uno. Todo lo demás pasó a tarjetas con vista propia. -->
      <section v-if="equiposUltimaMilla.length > 0" class="servicio-detalle__equipos" aria-label="Equipos de última milla">
        <span class="servicio-detalle__historico-label">Equipos de última milla</span>
        <div class="servicio-detalle__equipos-grid">
          <div v-for="equipo in equiposUltimaMilla" :key="equipo.extremo" class="servicio-detalle__equipo-card">
            <span class="servicio-detalle__equipo-extremo">Extremo {{ equipo.extremo }}</span>
            <span>{{ equipo.nodo || 'Nodo sin dato' }}</span>
            <span>{{ equipo.equipo || 'Equipo sin dato' }} · Puerto {{ equipo.puerto || '—' }}</span>
          </div>
        </div>
      </section>

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

      <!-- La densidad de esta ficha era el problema reportado: 9 bloques, con tablas enteras de
           ODFs y de ingresos compitiendo por la pantalla. Ahora cada sección resume en una tarjeta
           y se abre entera en su propia ruta, que además es linkeable. -->
      <section class="servicio-detalle__secciones" aria-label="Secciones del Servicio">
        <ServicioSeccionCard
          titulo="Histórico de IDs"
          icono="ph-clock-counter-clockwise"
          :to="rutaSeccion('historico')"
          :badge="timelineEvents.length || null"
          accion="Ver histórico completo"
        >
          <div class="servicio-detalle__historico-card">
            <ServiceTimeline :events="timelineEvents" />
            <p v-if="errorRefrescoProv" class="servicio-detalle__categoria-error">
              {{ errorRefrescoProv }}
            </p>
            <button
              class="btn subtle"
              type="button"
              :disabled="refrescandoProv"
              @click="onRefrescarDesdeProv"
            >
              <i :class="['ph', refrescandoProv ? 'ph-spinner' : 'ph-arrow-clockwise']" aria-hidden="true"></i>
              {{ refrescandoProv ? 'Actualizando…' : 'Actualizar desde PROV' }}
            </button>
          </div>
        </ServicioSeccionCard>

        <ServicioSeccionCard
          titulo="Camino óptico"
          icono="ph-path"
          :to="rutaSeccion('camino')"
          :badge="camino.cargandoPelos.value ? null : camino.pelos.value.length || null"
          :cargando="foLoading || camino.cargandoPelos.value"
          :error="foError"
          :resumen="resumenCamino"
          accion="Ver camino, ODFs y trackings"
        />

        <ServicioSeccionCard
          titulo="Ingresos"
          icono="ph-sign-in"
          :to="rutaSeccion('ingresos')"
          :badge="ingresosLoading ? null : ingresos.length || null"
          :cargando="ingresosLoading"
          :error="ingresosError"
          :resumen="resumenIngresos"
        />

        <ServicioSeccionCard
          titulo="Reclamos"
          icono="ph-warning-circle"
          :to="rutaSeccion('reclamos')"
          :badge="reclamosCount || null"
          :resumen="resumenReclamos"
        />

        <ServicioSeccionCard
          titulo="Eventos de baneo"
          icono="ph-shield-warning"
          :to="rutaSeccion('baneos')"
          :badge="baneosLoading ? null : baneosTotal || null"
          :badge-token="baneosActivos > 0 ? 'error' : 'idle'"
          :cargando="baneosLoading"
          :error="baneosError"
          :resumen="resumenBaneos"
        />
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import {
  CATEGORIAS_SERVICIO,
  categoriaLabel,
  estadoServicioToken,
  getServicioDetail,
  historialIdsToTimelineEvents,
  refrescarServicioDesdeProv,
  updateServicioCategoria,
  updateServicioVerificable,
  type ServicioEquipoUltimaMillaItem,
  type ServicioHistorialIdItem,
  type ServicioItem,
} from '../api/servicios';
import {
  type InfraRutaItem,
  type InfraServicioIngreso,
  type ReportHistoryItem,
  getBaneosServicio,
  getIngresosServicio,
  getOdfsServicio,
  getRutasServicio,
  getTrackingRuta,
  getUltimoReporte,
} from '../api/servicioSecciones';
import ServicioSeccionCard from '../components/servicios/detalle/ServicioSeccionCard.vue';
import ServiceTimeline from '../components/servicios/ServiceTimeline.vue';
import { useCromoPath } from '../composables/useCromoPath';
import { useSession } from '../composables/useSession';
import type { TimelineEvent } from '../types/timeline';

const route = useRoute();
const router = useRouter();
const { state } = useSession();
const isAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');

const servicio = ref<ServicioItem | null>(null);
const historialIds = ref<ServicioHistorialIdItem[]>([]);
const equiposUltimaMilla = ref<ServicioEquipoUltimaMillaItem[]>([]);
const refrescandoProv = ref(false);
const errorRefrescoProv = ref('');
const loading = ref(false);
const error = ref('');
const guardandoCategoria = ref(false);
const errorCategoria = ref('');
const guardandoVerificable = ref(false);
const errorVerificable = ref('');

// Los tipos y las llamadas de cada sección viven en `api/servicioSecciones.ts`: esta vista dejó de
// ser la única consumidora cuando cada sección pasó a tener su propia ruta, y tenerlos declarados
// acá obligaba a duplicarlos en las cinco vistas nuevas.

const foLoading = ref(false);
const foError = ref('');
const foRutas = ref<InfraRutaItem[]>([]);

// Sólo se usan las semillas y la descarga: la resolución completa del camino (con su auditoría)
// vive en el gestor de Servicios sin ODF, que es admin-only.
const camino = useCromoPath();

/**
 * La etiqueta dice cuántos archivos van a bajar, porque no es lo mismo un Servicio PON (1 pelo,
 * 1 .txt) que uno de FO o con un SW de módulo bifilar (2 o más). Durante la descarga muestra el
 * avance: en frío cada pelo cuesta entre 4,6 s y 14 s contra Cromo, así que sin progreso el
 * operador cree que se colgó.
 */
const etiquetaDescargaTracking = computed(() => {
  if (camino.descargando.value) {
    const total = camino.descargaTotal.value;
    return total > 1
      ? `Generando… ${camino.descargadosCount.value}/${total}`
      : 'Generando…';
  }
  const tildados = camino.pelosSeleccionados.value.length;
  return tildados > 1 ? `Trackings Cromo (${tildados} .txt)` : 'Tracking Cromo (.txt)';
});
const foTrackingResumen = ref<{
  camaras: number;
  cables: number;
  puntaA: string | null;
  puntaB: string | null;
} | null>(null);

// Sólo el total: las ODFs enteras se ven en la vista de Camino óptico (OdfsAsociadasPanel).
const totalOdfs = ref(0);

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

  // `alias_ids` mezcla dos dominios distintos: IDs numéricos históricos de línea (los que
  // arma `consolidar_identidad_servicio` en la ingesta SLA) y alias físicos de tracking FO
  // tipo "O1C1"/"C2" (los que agrega `execute_upgrade`/`_action_confirm_upgrade` en el módulo
  // de infraestructura, ver comentario de columna en `db/models/infra.py`). Sólo los primeros
  // pertenecen a esta cadena de "Histórico de IDs" — un alias físico no es un ID de línea.
  const alias = (servicio.value.alias_ids ?? [])
    .map((value) => (value ?? '').trim())
    .filter((value) => /^\d+$/.test(value))
    .sort((a, b) => Number(a) - Number(b));

  const ids = [servicio.value.numero_primer_servicio, ...alias, servicio.value.numero_linea]
    .map((value) => (value ?? '').trim())
    .filter((value, index, arr) => value.length > 0 && arr.indexOf(value) === index);

  return ids.length > 0 ? ids : [idParam.value];
});

const timelineEvents = computed<TimelineEvent[]>(() => {
  if (historialIds.value.length > 0) {
    return historialIdsToTimelineEvents(historialIds.value);
  }
  // Fallback para servicios que todavía no pasaron por un refresco/backfill de PROV: reusa la
  // misma cadena simple de `alias_ids` que mostraba el track horizontal anterior, sin
  // fecha/estado/motivo (esos datos sólo existen una vez que PROV enriqueció el servicio).
  return historicoIds.value.map((id, index) => ({
    id,
    fecha: null,
    tipo: 'upgrade_id' as const,
    titulo: `ID ${id}`,
    descripcion: index === historicoIds.value.length - 1 ? 'Vigente' : undefined,
  }));
});

const reclamosCount = computed(() => servicio.value?.reclamos?.length ?? 0);

const baneosLoading = ref(false);
const baneosError = ref('');
const baneosTotal = ref(0);
const baneosActivos = ref(0);

/** URL de la vista dedicada de una sección, sobre el ID de origen ya normalizado. */
function rutaSeccion(seccion: string): string {
  // `idParam` ya es el ID de origen normalizado: `loadDetalle` hace `router.replace` hacia él
  // cuando la URL traía otro de los identificadores del Servicio.
  return `/servicios/ID/${encodeURIComponent(idParam.value)}/${seccion}`;
}

// Las tarjetas resumen en una línea: el detalle completo vive en la vista de cada sección.
const resumenCamino = computed(() => {
  const pelos = camino.pelos.value.length;
  const rutas = foRutas.value.length;
  const partes: string[] = [];
  partes.push(pelos === 1 ? '1 pelo en Cromo' : `${pelos} pelos en Cromo`);
  if (rutas) partes.push(rutas === 1 ? '1 ruta FO' : `${rutas} rutas FO`);
  if (totalOdfs.value) partes.push(totalOdfs.value === 1 ? '1 ODF' : `${totalOdfs.value} ODFs`);
  return partes.join(' · ');
});

const resumenIngresos = computed(() => {
  if (ingresos.value.length === 0) return 'Sin ingresos registrados';
  const abiertos = ingresos.value.filter((i) => !i.fecha_fin).length;
  return abiertos > 0
    ? `${ingresos.value.length} ingreso(s) · ${abiertos} sin cierre`
    : `${ingresos.value.length} ingreso(s)`;
});

const resumenReclamos = computed(() =>
  reclamosCount.value === 0
    ? 'Sin reclamos cargados'
    : `${reclamosCount.value} reclamo(s) · SLA ${slaEstadoCorto.value}`,
);

const resumenBaneos = computed(() => {
  if (baneosTotal.value === 0) return 'Nunca participó en un baneo';
  return baneosActivos.value > 0
    ? `${baneosTotal.value} evento(s) · ${baneosActivos.value} activo(s)`
    : `${baneosTotal.value} evento(s), ninguno activo`;
});

async function loadBaneos(servicioId: number): Promise<void> {
  baneosLoading.value = true;
  baneosError.value = '';
  try {
    const respuesta = await getBaneosServicio(servicioId);
    baneosTotal.value = respuesta.total;
    baneosActivos.value = respuesta.activos;
  } catch (err: unknown) {
    baneosTotal.value = 0;
    baneosActivos.value = 0;
    baneosError.value = err instanceof Error ? err.message : 'No se pudieron cargar los baneos';
  } finally {
    baneosLoading.value = false;
  }
}
const estadoToken = computed(() => estadoServicioToken(servicio.value?.estado_servicio));

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

/** Descarga el tracking `.txt` generado desde Cromo para el Servicio abierto. */
async function descargarTrackingDeCromo(): Promise<void> {
  const servicioId = servicio.value?.id;
  if (servicioId == null) return;
  await camino.descargarTrackings(servicioId);
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
    historialIds.value = response.historial_ids;
    equiposUltimaMilla.value = response.equipos_ultima_milla;

    await Promise.all([
      loadFoResumen(response.id_origen),
      loadReportesResumen(),
      loadOdfsAsociadas(response.id_origen),
      loadIngresosAsociados(response.id_origen),
      // Semillas: SQL local, no toca Cromo. Se piden acá para que el botón sepa si va habilitado
      // ANTES del click, en vez de hacerle descubrir al operador que no hay camino recién después.
      // Prioridad por conector: acá los pelos que importan son las posiciones de ODF del
      // Servicio, al revés que en el gestor de Servicios sin ODF.
      camino.cargarPelos(response.servicio.id, { priorizarConector: true }),
      loadBaneos(response.servicio.id),
    ]);

    const idOrigen = response.id_origen.trim();
    if (idOrigen && idOrigen !== id) {
      await router.replace(`/servicios/ID/${encodeURIComponent(idOrigen)}`);
    }
  } catch (err: unknown) {
    servicio.value = null;
    historialIds.value = [];
    equiposUltimaMilla.value = [];
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

async function onRefrescarDesdeProv(): Promise<void> {
  if (!servicio.value || refrescandoProv.value) return;
  refrescandoProv.value = true;
  errorRefrescoProv.value = '';
  try {
    const response = await refrescarServicioDesdeProv(idParam.value);
    servicio.value = response.servicio;
    historialIds.value = response.historial_ids;
    equiposUltimaMilla.value = response.equipos_ultima_milla;
  } catch (err: unknown) {
    errorRefrescoProv.value = err instanceof Error ? err.message : 'No se pudo actualizar desde PROV';
  } finally {
    refrescandoProv.value = false;
  }
}

async function loadFoResumen(idOrigen: string): Promise<void> {
  const clean = idOrigen.trim();
  if (!clean) return;

  foLoading.value = true;
  foError.value = '';
  foRutas.value = [];
  foTrackingResumen.value = null;

  try {
    const rutasData = await getRutasServicio(clean);
    foRutas.value = rutasData.rutas ?? [];

    const principal = rutaPrincipal.value;
    if (!principal) return;

    const trackingData = await getTrackingRuta(principal.id);
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

/** Alimenta el "N ODFs" del resumen de la tarjeta de Camino. Si falla, el resumen omite esa parte
 * en vez de gritar: el detalle -y su error, con texto- vive en la vista de Camino óptico. */
async function loadOdfsAsociadas(idOrigen: string): Promise<void> {
  const clean = idOrigen.trim();
  totalOdfs.value = 0;
  if (!clean) return;

  try {
    const data = await getOdfsServicio(clean);
    totalOdfs.value = data.total_odfs ?? 0;
  } catch {
    totalOdfs.value = 0;
  }
}

async function loadIngresosAsociados(idOrigen: string): Promise<void> {
  const clean = idOrigen.trim();
  if (!clean) return;

  ingresosLoading.value = true;
  ingresosError.value = '';
  ingresos.value = [];

  try {
    const data = await getIngresosServicio(clean);
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
    const [slaData, repData] = await Promise.all([
      getUltimoReporte('sla'),
      getUltimoReporte('repetitividad'),
    ]);

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

/** Hasta ahora esta vista sólo descargaba el .txt; con el panel puede quedar una resolución de
 * hasta 30 s en vuelo al navegar a otro Servicio o salir. `cancelar()` aborta la request y limpia
 * los temporizadores del composable. */
onBeforeUnmount(() => camino.cancelar());
</script>

<style scoped>
.servicio-detalle {
  padding-bottom: 26px;
}

.servicio-detalle__migas {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 16px 0 0;
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
  padding: 14px 0 18px;
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

/* Columna, no fila: los hijos son el header (label + botón), el error de refresco y el
   `<ServiceTimeline>` vertical — apilados. En fila, el Timeline quedaba comprimido al costado del
   header. El track horizontal de IDs que justificaba `align-items: center` ya no existe (lo
   reemplazó el Timeline). */
.servicio-detalle__historico {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 11px;
  padding: 16px 0;
}

.servicio-detalle__historico-label {
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-neutral-500);
}

.servicio-detalle__historico-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

/* Mismo padding horizontal (26px) que el resto de las secciones de la vista: sin él, esta sección
   quedaba pegada al borde izquierdo, desalineada de la cabecera y del histórico. */
.servicio-detalle__equipos {
  padding: 0 26px 16px;
}

.servicio-detalle__equipos-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 8px;
}

.servicio-detalle__equipo-card {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 14px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  font-size: 0.85rem;
}

.servicio-detalle__equipo-extremo {
  font-weight: 700;
  font-size: 0.75rem;
  color: var(--muted);
  text-transform: uppercase;
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
