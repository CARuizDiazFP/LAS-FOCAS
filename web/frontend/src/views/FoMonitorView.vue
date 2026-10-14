<!--
  Nombre de archivo: FoMonitorView.vue
  Ubicación de archivo: web/frontend/src/views/FoMonitorView.vue
  Descripción: Módulo FO Monitor — mapa de cables con semáforo PRE/POST por intervención, lista, ficha y control del piloto
-->
<template>
  <section class="fomon">
    <header class="fomon__header">
      <div>
        <h1>FO Monitor</h1>
        <p class="section-subtitle">
          Estado de los servicios de cada cable antes y después de un ingreso a cámara o botella, verificado con burritoIA.
        </p>
      </div>
      <ul class="fomon__leyenda" aria-label="Leyenda del semáforo">
        <li v-for="(texto, color) in ETIQUETA_COLOR" :key="color">
          <span class="fomon-punto" :class="`is-${String(color).toLowerCase()}`"></span>{{ texto }}
        </li>
      </ul>
    </header>

    <div class="fomon__cuerpo">
      <FoMonitorMap
        ref="mapaRef"
        class="fomon__mapa"
        :intervenciones="geoIntervenciones"
        :cable-seleccionado="seleccion?.cableNId ?? null"
        :geo-servicios="geoServicios"
        :servicios-resaltados="geoServicios?.servicios ?? []"
        @seleccionar="seleccionar"
        @agregar-servicios="agregarServicios"
        @quitar-servicio="quitarServicio"
      />

      <aside class="fomon__lateral">
        <CableFichaPanel
          v-if="seleccion && seleccion.intervencionId === null"
          :cable-n-id="seleccion.cableNId"
          :seleccionados="serviciosSeleccionados"
          :colores="coloresPorServicio"
          @cerrar="seleccion = null"
          @abrir-intervencion="abrirIntervencionPorId"
          @alternar-servicio="alternarServicio"
        />
        <CableDetailPanel
          v-else-if="seleccion"
          :cable-n-id="seleccion.cableNId"
          :intervencion-id="seleccion.intervencionId"
          :es-admin="esAdmin"
          :version="version"
          @cerrar="seleccion = null"
          @abrir-intervencion="abrirIntervencionPorId"
        />
        <IntervencionesPanel v-else :listado="listado" @abrir="abrirIntervencion" @filtrar="filtrar" />

        <article v-if="esAdmin" class="card fomon__admin">
          <details>
            <summary>Piloto y verificación manual</summary>
            <p v-if="adminError" class="msg err visible">{{ adminError }}</p>
            <div v-if="config" class="fomon__piloto">
              <label class="fomon__switch">
                <input type="checkbox" :checked="config.activo" @change="cambiarActivo(($event.target as HTMLInputElement).checked)" />
                Piloto activo
              </label>
              <small>
                Mensajes a burritoIA hoy: {{ config.mensajes_hoy }} / {{ config.tope_mensajes_diario }} ·
                prompt {{ config.prompt_version }} · lote {{ config.max_ids_por_mensaje }} ·
                canales de ingreso verificados: {{ config.canales_ingreso || 'todos' }}
              </small>
              <div class="fomon__ventana">
                <label>Ventana desde <input v-model="ventana.desde" type="datetime-local" /></label>
                <label>hasta <input v-model="ventana.hasta" type="datetime-local" /></label>
                <button class="btn subtle" type="button" @click="guardarVentana">Guardar ventana</button>
                <button class="btn subtle" type="button" @click="ventana24h">Próximas 24 h</button>
              </div>
            </div>
            <form class="fomon__manual" @submit.prevent="verificarManual">
              <select v-model="manual.tipo" aria-label="Tipo de objetivo">
                <option value="camara_id">Cámara (id)</option>
                <option value="botella_n_id">Botella (n_id)</option>
                <option value="cable_n_id">Cable (n_id)</option>
              </select>
              <input v-model="manual.valor" type="text" inputmode="numeric" placeholder="Id…" aria-label="Id" />
              <button class="btn primary" type="submit" :disabled="!manual.valor">Verificar ahora</button>
            </form>
            <p v-if="manualOk" class="hint">{{ manualOk }}</p>
          </details>
        </article>
      </aside>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import {
  actualizarConfigPiloto, crearVerificacionManual, leerConfigPiloto, listarIntervenciones, obtenerGeoServicios,
  obtenerMapaIntervenciones, type ConfigPiloto, type FiltrosIntervenciones, type GeoServicios, type IntervencionResumen,
  type ListadoIntervenciones,
} from '../api/foMonitor';
import CableDetailPanel from '../components/fo-monitor/CableDetailPanel.vue';
import CableFichaPanel from '../components/fo-monitor/CableFichaPanel.vue';
import FoMonitorMap from '../components/fo-monitor/FoMonitorMap.vue';
import IntervencionesPanel from '../components/fo-monitor/IntervencionesPanel.vue';
import { ETIQUETA_COLOR, colorServicio } from '../components/fo-monitor/colores';
import { useFoMonitorPolling } from '../composables/useFoMonitorPolling';
import { useSession } from '../composables/useSession';

const { state } = useSession();
const esAdmin = computed(() => (state.value.role ?? '').toLowerCase() === 'admin');

const mapaRef = ref<InstanceType<typeof FoMonitorMap> | null>(null);
const geoIntervenciones = ref<GeoJSON.FeatureCollection | null>(null);
const listado = ref<ListadoIntervenciones | null>(null);
const filtros = ref<FiltrosIntervenciones>({ estado: 'ACTIVAS', limit: 50 });
const seleccion = ref<{ cableNId: number; intervencionId: number | null } | null>(null);
const version = ref(0);

// Servicios resaltados en el mapa (máx. 8), cada uno con su color de PALETA_SERVICIOS por posición.
const MAX_SERVICIOS = 8;
const serviciosSeleccionados = ref<string[]>([]);
const geoServicios = ref<GeoServicios | null>(null);
const coloresPorServicio = computed<Record<string, string>>(() =>
  Object.fromEntries(serviciosSeleccionados.value.map((id, i) => [id, colorServicio(i)])),
);
let controladorServicios: AbortController | null = null;

async function cargarServicios(enfocarResultado: boolean): Promise<void> {
  controladorServicios?.abort();
  if (serviciosSeleccionados.value.length === 0) {
    geoServicios.value = null;
    return;
  }
  controladorServicios = new AbortController();
  try {
    geoServicios.value = await obtenerGeoServicios(serviciosSeleccionados.value, controladorServicios.signal);
    if (enfocarResultado) {
      mapaRef.value?.enfocar(
        geoServicios.value.features.flatMap((f) => (f.geometry as GeoJSON.LineString).coordinates as [number, number][]),
      );
    }
  } catch (err) {
    if ((err as Error).name !== 'AbortError') console.warn('fo-monitor servicios', err);
  }
}

function agregarServicios(ids: string[]): void {
  const nuevos = ids.filter((id) => !serviciosSeleccionados.value.includes(id));
  serviciosSeleccionados.value = [...serviciosSeleccionados.value, ...nuevos].slice(0, MAX_SERVICIOS);
  void cargarServicios(true);
}

function quitarServicio(id: string): void {
  serviciosSeleccionados.value = serviciosSeleccionados.value.filter((x) => x !== id);
  void cargarServicios(false);
}

function alternarServicio(id: string): void {
  if (serviciosSeleccionados.value.includes(id)) quitarServicio(id);
  else agregarServicios([id]);
}

const config = ref<ConfigPiloto | null>(null);
const adminError = ref('');
const ventana = reactive({ desde: '', hasta: '' });
const manual = reactive({ tipo: 'camara_id' as 'camara_id' | 'botella_n_id' | 'cable_n_id', valor: '' });
const manualOk = ref('');

const { refrescar } = useFoMonitorPolling(async (signal) => {
  const [geo, lista] = await Promise.all([
    obtenerMapaIntervenciones(24, signal),
    listarIntervenciones(filtros.value, signal),
  ]);
  geoIntervenciones.value = geo;
  listado.value = lista;
  version.value += 1;
});

function seleccionar(payload: { cableNId: number; intervencionId: number | null }): void {
  seleccion.value = payload;
}

function coordsDeIntervencion(id: number): [number, number][] {
  const features = geoIntervenciones.value?.features ?? [];
  return features
    .filter((f) => f.properties?.intervencion_id === id && f.geometry.type === 'LineString')
    .flatMap((f) => (f.geometry as GeoJSON.LineString).coordinates as [number, number][]);
}

function abrirIntervencion(i: IntervencionResumen): void {
  const features = (geoIntervenciones.value?.features ?? []).filter((f) => f.properties?.intervencion_id === i.id);
  const objetivo = features.find((f) => f.properties?.es_objetivo) ?? features[0];
  const cableNId = objetivo ? Number(objetivo.properties?.cable_n_id) : i.cable_n_id_manual;
  if (!cableNId) return;
  seleccion.value = { cableNId, intervencionId: i.id };
  mapaRef.value?.enfocar(coordsDeIntervencion(i.id));
}

function abrirIntervencionPorId(id: number): void {
  if (seleccion.value) seleccion.value = { cableNId: seleccion.value.cableNId, intervencionId: id };
}

function filtrar(f: FiltrosIntervenciones): void {
  filtros.value = { ...f, limit: 50 };
  void refrescar();
}

function aLocal(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

async function cargarConfig(): Promise<void> {
  if (!esAdmin.value) return;
  try {
    config.value = await leerConfigPiloto();
    ventana.desde = aLocal(config.value.ventana_desde);
    ventana.hasta = aLocal(config.value.ventana_hasta);
  } catch (err) {
    adminError.value = (err as Error).message;
  }
}

async function guardar(cambios: Partial<ConfigPiloto>): Promise<void> {
  adminError.value = '';
  try {
    config.value = await actualizarConfigPiloto(cambios);
  } catch (err) {
    adminError.value = (err as Error).message;
  }
}

function cambiarActivo(activo: boolean): void {
  void guardar({ activo });
}

function guardarVentana(): void {
  void guardar({
    ventana_desde: ventana.desde ? new Date(ventana.desde).toISOString() : null,
    ventana_hasta: ventana.hasta ? new Date(ventana.hasta).toISOString() : null,
  });
}

function ventana24h(): void {
  const ahora = new Date();
  ventana.desde = aLocal(ahora.toISOString());
  ventana.hasta = aLocal(new Date(ahora.getTime() + 24 * 3600_000).toISOString());
  guardarVentana();
}

async function verificarManual(): Promise<void> {
  adminError.value = '';
  manualOk.value = '';
  const id = Number(manual.valor);
  if (!Number.isInteger(id) || id <= 0) {
    adminError.value = 'Id inválido';
    return;
  }
  try {
    const r = await crearVerificacionManual({ [manual.tipo]: id });
    manualOk.value = `Verificación #${r.intervencion_id} creada: el worker la toma en el próximo ciclo (≈10 s).`;
    manual.valor = '';
    void refrescar();
  } catch (err) {
    adminError.value = (err as Error).message;
  }
}

onMounted(cargarConfig);
</script>

<style scoped>
.fomon {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 20px 0 24px;
  height: calc(100vh - 40px);
  min-height: 560px;
}

.fomon__header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-end;
  gap: 12px;
}

.fomon__header h1 {
  margin: 4px 0 6px;
}

.fomon__leyenda {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 12px;
  color: var(--color-text-muted);
}

.fomon__leyenda li {
  display: flex;
  align-items: center;
  gap: 6px;
}

.fomon__cuerpo {
  flex: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 14px;
  min-height: 0;
}

.fomon__lateral {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  min-height: 0;
}

.fomon__admin {
  padding: 12px 16px;
  font-size: 13px;
}

.fomon__admin summary {
  cursor: pointer;
  color: var(--color-text-muted);
}

.fomon__piloto,
.fomon__manual,
.fomon__ventana {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.fomon__piloto small {
  color: var(--color-text-muted);
}

@media (max-width: 1100px) {
  .fomon {
    height: auto;
  }

  .fomon__cuerpo {
    grid-template-columns: 1fr;
  }

  .fomon__mapa {
    height: 60vh;
  }
}
</style>

<style>
/* Punto de color del semáforo: compartido por la vista, la lista y la ficha (estilo global acotado al prefijo). */
.fomon-punto {
  display: inline-block;
  width: 10px;
  height: 10px;
  flex: none;
  border-radius: var(--radius-pill);
  background: var(--color-state-idle);
}

.fomon-punto.is-verde { background: var(--color-state-ok); }
.fomon-punto.is-amarillo { background: var(--color-state-warn); }
.fomon-punto.is-naranja { background: var(--color-state-degraded); }
.fomon-punto.is-rojo { background: var(--color-state-error); }
.fomon-punto.is-gris { background: var(--color-state-idle); }
</style>
