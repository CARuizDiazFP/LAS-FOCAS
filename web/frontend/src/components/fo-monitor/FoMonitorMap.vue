<!--
  Nombre de archivo: FoMonitorMap.vue
  Ubicación de archivo: web/frontend/src/components/fo-monitor/FoMonitorMap.vue
  Descripción: Mapa MapLibre de FO Monitor — red FO en gris, cables de intervenciones por color de semáforo y botellas
-->
<template>
  <div class="fomon-mapa">
    <div ref="contenedor" class="fomon-mapa__lienzo" role="region" aria-label="Mapa de cables FO"></div>
    <div class="fomon-mapa__panel card">
      <form class="fomon-mapa__buscar" @submit.prevent="buscar">
        <select v-model="tipoBusqueda" aria-label="Buscar por">
          <option value="servicio">Servicio</option>
          <option value="cable">Cable</option>
          <option value="camara">Cámara</option>
        </select>
        <input v-model="textoBusqueda" class="fomon-mapa__texto" type="search" :placeholder="placeholderBusqueda" aria-label="Texto a buscar" />
        <button class="btn primary" type="submit" :disabled="buscando || textoBusqueda.trim().length < 2" aria-label="Buscar">
          <i class="ph ph-magnifying-glass" aria-hidden="true"></i>
        </button>
        <button v-if="resumenBusqueda" class="btn subtle" type="button" aria-label="Limpiar búsqueda" @click="limpiarBusqueda">
          <i class="ph ph-x" aria-hidden="true"></i>
        </button>
      </form>
      <small v-if="resumenBusqueda" class="fomon-mapa__resumen">{{ resumenBusqueda }}</small>
      <ul v-if="serviciosResaltados.length" class="fomon-mapa__chips" aria-label="Servicios resaltados">
        <li v-for="sv in serviciosResaltados" :key="sv.q" :class="{ 'is-no-encontrado': !sv.encontrado }">
          <span class="fomon-mapa__muestra" :style="{ background: PALETA_SERVICIOS[sv.indice % PALETA_SERVICIOS.length] }"></span>
          <span :title="sv.cliente || ''">{{ sv.q }}</span>
          <small>{{ sv.encontrado ? `${sv.cables} cable(s)` : 'no encontrado' }}</small>
          <button type="button" class="fomon-mapa__quitar" :aria-label="`Quitar ${sv.q}`" @click="emit('quitar-servicio', sv.q)">
            <i class="ph ph-x" aria-hidden="true"></i>
          </button>
        </li>
      </ul>
      <label><input v-model="verRed" type="checkbox" /> Red FO completa <small>(≈ 1,5 MB, carga bajo demanda)</small></label>
      <label><input v-model="verBotellas" type="checkbox" /> Botellas (zoom ≥ 15)</label>
      <small v-if="cargandoRed" class="fomon-mapa__resumen">Cargando red…</small>
    </div>
    <p v-if="avisoBase" class="fomon-mapa__aviso">{{ avisoBase }}</p>
  </div>
</template>

<script setup lang="ts">
import * as maplibregl from 'maplibre-gl';
import type { GeoJSONSource, StyleSpecification } from 'maplibre-gl';
// MapLibre v6 calcula la URL de su worker en runtime (`new URL('./maplibre-gl-worker.mjs',
// import.meta.url)`), así que Vite no lo emite y el mapa nunca termina de cargar (dev 2026-10-14: sólo
// se pedía el header del PMTiles). `?worker&url` lo empaqueta con su chunk compartido y lo registramos.
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { layers, namedFlavor } from '@protomaps/basemaps';
import { Protocol } from 'pmtiles';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import {
  buscarEnMapa, obtenerMapaBotellas, obtenerMapaConfig, obtenerMapaRed, type ColorSemaforo, type GeoServicios, type MapaConfig, type ServicioResaltado,
  type TipoBusquedaMapa,
} from '../../api/foMonitor';
import { PALETA_SERVICIOS, paletaSemaforo, resolverColor, resolverToken } from './colores';

const props = defineProps<{
  intervenciones: GeoJSON.FeatureCollection | null;
  cableSeleccionado: number | null;
  geoServicios: GeoServicios | null;
  serviciosResaltados: ServicioResaltado[];
}>();
const emit = defineEmits<{
  (e: 'seleccionar', payload: { cableNId: number; intervencionId: number | null }): void;
  (e: 'agregar-servicios', ids: string[]): void;
  (e: 'quitar-servicio', id: string): void;
}>();

const contenedor = ref<HTMLDivElement | null>(null);
// La red completa (~34k cables, ~8 MB sin comprimir) no se baja de entrada: se busca por servicio,
// cable o cámara, o se activa a pedido (feedback del usuario 2026-10-14).
const verRed = ref(false);
const cargandoRed = ref(false);
const verBotellas = ref(false);
const avisoBase = ref('');
const tipoBusqueda = ref<TipoBusquedaMapa>('servicio');
const textoBusqueda = ref('');
const buscando = ref(false);
const resumenBusqueda = ref('');
const placeholderBusqueda = computed(() =>
  ({ servicio: 'N° de servicio (varios: 117995, 113705)…', cable: 'Nombre o n_id del cable…', camara: 'Nombre o id de cámara…' })[tipoBusqueda.value],
);
let mapa: maplibregl.Map | null = null;
let protocolo: Protocol | null = null;
const CENTRO_AMBA: [number, number] = [-58.45, -34.62];
const VACIO: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] };

function estiloBase(cfg: MapaConfig): StyleSpecification {
  const origen = window.location.origin;
  if (cfg.modo === 'local') {
    return {
      version: 8,
      glyphs: `${origen}${cfg.glyphs_url}`,
      sprite: `${origen}${cfg.sprite_url}`,
      sources: {
        protomaps: { type: 'vector', url: `pmtiles://${origen}${cfg.pmtiles_url}`, attribution: '© OpenStreetMap' },
      },
      layers: layers('protomaps', namedFlavor('dark'), { lang: 'es' }),
    };
  }
  // Plan B (FOMON_BASEMAP_MODO=osm o sin PMTiles descargado): raster OSM, requiere salida a Internet.
  return {
    version: 8,
    sources: {
      osm: {
        type: 'raster',
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors',
      },
    },
    layers: [{ id: 'osm', type: 'raster', source: 'osm', paint: { 'raster-brightness-max': 0.55 } }],
  };
}

function expresionColor(paleta: Record<ColorSemaforo, string>): maplibregl.ExpressionSpecification {
  return ['match', ['get', 'color'], 'VERDE', paleta.VERDE, 'AMARILLO', paleta.AMARILLO, 'NARANJA', paleta.NARANJA,
    'ROJO', paleta.ROJO, paleta.GRIS];
}

async function cargarRed(): Promise<void> {
  if (!mapa || mapa.getSource('red')) return;
  cargandoRed.value = true;
  const red = await obtenerMapaRed().finally(() => {
    cargandoRed.value = false;
  });
  if (!mapa || mapa.getSource('red')) return;
  mapa.addSource('red', { type: 'geojson', data: red, tolerance: 0.6 });
  mapa.addLayer(
    {
      id: 'red-linea',
      type: 'line',
      source: 'red',
      paint: { 'line-color': resolverToken('--color-neutral-600'), 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.4, 16, 1.6], 'line-opacity': 0.7 },
      layout: { visibility: verRed.value ? 'visible' : 'none' },
    },
    'interv-linea',
  );
}

async function cargarBotellas(): Promise<void> {
  if (!mapa || !verBotellas.value || mapa.getZoom() < 15) return;
  const b = mapa.getBounds();
  const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(',');
  const datos = await obtenerMapaBotellas(bbox);
  (mapa.getSource('botellas') as GeoJSONSource | undefined)?.setData(datos);
}

function actualizarIntervenciones(): void {
  (mapa?.getSource('interv') as GeoJSONSource | undefined)?.setData(props.intervenciones ?? VACIO);
}

onMounted(async () => {
  const cfg = await obtenerMapaConfig().catch(() => null);
  if (!cfg || !contenedor.value) return;
  if (cfg.modo === 'osm') {
    avisoBase.value = cfg.pmtiles_disponible ? '' : 'Mapa base externo (OSM): el PMTiles local todavía no está instalado.';
  }
  maplibregl.setWorkerUrl(workerUrl);
  protocolo = new Protocol();
  maplibregl.addProtocol('pmtiles', protocolo.tile);
  mapa = new maplibregl.Map({ container: contenedor.value, style: estiloBase(cfg), center: CENTRO_AMBA, zoom: 11, attributionControl: { compact: true } });
  mapa.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

  mapa.on('load', () => {
    if (!mapa) return;
    const paleta = paletaSemaforo();
    mapa.addSource('interv', { type: 'geojson', data: props.intervenciones ?? VACIO, tolerance: 0 });
    mapa.addLayer({
      id: 'interv-linea',
      type: 'line',
      source: 'interv',
      paint: {
        'line-color': expresionColor(paleta),
        'line-width': ['case', ['==', ['get', 'cable_n_id'], props.cableSeleccionado ?? -1], 7, ['get', 'es_objetivo'], 5, 3.5],
      },
      layout: { 'line-cap': 'round', 'line-join': 'round' },
    });
    mapa.addSource('botellas', { type: 'geojson', data: VACIO });
    mapa.addLayer({
      id: 'botellas-punto',
      type: 'circle',
      source: 'botellas',
      minzoom: 15,
      paint: { 'circle-radius': 4, 'circle-color': resolverToken('--color-bg'), 'circle-stroke-width': 1.5,
        'circle-stroke-color': resolverToken('--color-neutral-300') },
    });
    mapa.addSource('busqueda', { type: 'geojson', data: VACIO, tolerance: 0 });
    mapa.addLayer({
      id: 'busqueda-linea',
      type: 'line',
      source: 'busqueda',
      paint: {
        'line-color': resolverToken('--color-neutral-200'),
        'line-width': ['interpolate', ['linear'], ['zoom'], 9, 2, 13, 3, 16, 4.5],
        'line-opacity': 0.9,
      },
      layout: { 'line-cap': 'round', 'line-join': 'round' },
    }, 'interv-linea');
    const paletaRgb = PALETA_SERVICIOS.map((c) => resolverColor(c));
    // tolerance 0: estas capas tienen pocos cables y con la simplificación por defecto (0,375) los
    // tramos cortos desaparecían al alejar el zoom y el camino se veía cortado (dev 2026-10-14).
    mapa.addSource('servicios', { type: 'geojson', data: props.geoServicios ?? VACIO, tolerance: 0 });
    mapa.addLayer({
      id: 'servicios-linea',
      type: 'line',
      source: 'servicios',
      paint: {
        'line-color': ['match', ['get', 'indice'], ...paletaRgb.flatMap((c, i) => [i, c]), paletaRgb[0]] as unknown as maplibregl.ExpressionSpecification,
        'line-width': ['interpolate', ['linear'], ['zoom'], 9, 2, 13, 3, 16, 4.5],
        // Un cable compartido por varios servicios se dibuja como líneas paralelas, una por servicio,
        // sólo de cerca: de lejos el desplazamiento fijo descentraba los caminos, así que hasta z12 van
        // centrados (superpuestos) y se separan progresivamente hasta z15.
        'line-offset': ['interpolate', ['linear'], ['zoom'], 12, 0, 15, ['*', ['get', 'indice'], 4]],
      },
      layout: { 'line-cap': 'round', 'line-join': 'round' },
    }, 'interv-linea');
    if (verRed.value) void cargarRed();
    mapa.on('click', 'servicios-linea', (ev) => {
      if (mapa?.queryRenderedFeatures(ev.point, { layers: ['interv-linea'] }).length) return;
      const p = ev.features?.[0]?.properties;
      if (p) emit('seleccionar', { cableNId: Number(p.cable_n_id), intervencionId: null });
    });
    mapa.on('click', 'busqueda-linea', (ev) => {
      if (mapa?.queryRenderedFeatures(ev.point, { layers: ['servicios-linea'] }).length) return;
      if (mapa?.queryRenderedFeatures(ev.point, { layers: ['interv-linea'] }).length) return;
      const p = ev.features?.[0]?.properties;
      if (p) emit('seleccionar', { cableNId: Number(p.cable_n_id), intervencionId: null });
    });
    mapa.on('click', 'interv-linea', (ev) => {
      const p = ev.features?.[0]?.properties;
      if (p) emit('seleccionar', { cableNId: Number(p.cable_n_id), intervencionId: Number(p.intervencion_id) });
    });
    mapa.on('click', 'red-linea', (ev) => {
      if (mapa?.queryRenderedFeatures(ev.point, { layers: ['interv-linea', 'servicios-linea', 'busqueda-linea'] }).length) return;
      const p = ev.features?.[0]?.properties;
      if (p) emit('seleccionar', { cableNId: Number(p.id), intervencionId: null });
    });
    for (const capa of ['interv-linea', 'red-linea', 'busqueda-linea', 'servicios-linea']) {
      mapa.on('mouseenter', capa, () => { if (mapa) mapa.getCanvas().style.cursor = 'pointer'; });
      mapa.on('mouseleave', capa, () => { if (mapa) mapa.getCanvas().style.cursor = ''; });
    }
    mapa.on('moveend', () => void cargarBotellas());
  });
});

watch(() => props.intervenciones, actualizarIntervenciones);
watch(() => props.cableSeleccionado, (id) => {
  mapa?.setPaintProperty('interv-linea', 'line-width',
    ['case', ['==', ['get', 'cable_n_id'], id ?? -1], 7, ['get', 'es_objetivo'], 5, 3.5]);
});
watch(verRed, (v) => {
  if (mapa?.getLayer('red-linea')) mapa.setLayoutProperty('red-linea', 'visibility', v ? 'visible' : 'none');
  else if (v) void cargarRed();
});

watch(() => props.geoServicios, (fc) => {
  (mapa?.getSource('servicios') as GeoJSONSource | undefined)?.setData(fc ?? VACIO);
});

async function buscar(): Promise<void> {
  if (!mapa) return;
  if (tipoBusqueda.value === 'servicio') {
    const ids = textoBusqueda.value.split(/[\s,;]+/).map((x) => x.trim()).filter(Boolean);
    if (ids.length) emit('agregar-servicios', ids);
    textoBusqueda.value = '';
    return;
  }
  buscando.value = true;
  try {
    const r = await buscarEnMapa(tipoBusqueda.value, textoBusqueda.value.trim());
    (mapa.getSource('busqueda') as GeoJSONSource | undefined)?.setData(r);
    const m = r.meta;
    resumenBusqueda.value = m.encontrados === 0
      ? 'Sin coincidencias.'
      : `${m.con_geometria} cable(s) en el mapa${m.truncado ? ' (resultado truncado, refiná la búsqueda)' : ''}` +
        (m.con_geometria < m.encontrados ? ` · ${m.encontrados - m.con_geometria} sin trazado` : '');
    enfocar(r.features.flatMap((f) => (f.geometry as GeoJSON.LineString).coordinates as [number, number][]));
  } catch (err) {
    resumenBusqueda.value = (err as Error).message;
  } finally {
    buscando.value = false;
  }
}

function limpiarBusqueda(): void {
  (mapa?.getSource('busqueda') as GeoJSONSource | undefined)?.setData(VACIO);
  resumenBusqueda.value = '';
  textoBusqueda.value = '';
}
watch(verBotellas, (v) => {
  if (v) void cargarBotellas();
  else (mapa?.getSource('botellas') as GeoJSONSource | undefined)?.setData(VACIO);
});

function enfocar(coords: [number, number][]): void {
  if (!mapa || coords.length === 0) return;
  const caja = coords.reduce((b, c) => b.extend(c), new maplibregl.LngLatBounds(coords[0], coords[0]));
  mapa.fitBounds(caja, { padding: 80, maxZoom: 16, duration: 600 });
}

defineExpose({ enfocar });

onBeforeUnmount(() => {
  mapa?.remove();
  mapa = null;
  maplibregl.removeProtocol('pmtiles');
});
</script>

<style scoped>
.fomon-mapa {
  position: relative;
  height: 100%;
  min-height: 420px;
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.fomon-mapa__lienzo {
  position: absolute;
  inset: 0;
}

.fomon-mapa__panel {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: min(460px, calc(100% - 70px));
  box-sizing: border-box;
  padding: 8px 10px;
  font-size: 12px;
}

.fomon-mapa__buscar {
  display: grid;
  grid-template-columns: 110px minmax(200px, 1fr) auto auto;
  gap: 6px;
  align-items: stretch;
}

.fomon-mapa__buscar select,
.fomon-mapa__texto {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
}

.fomon-mapa__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.fomon-mapa__chips li {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 2px 4px 2px 8px;
  border-radius: var(--radius-pill);
  background: var(--color-bg-surface-alt);
}

.fomon-mapa__chips li.is-no-encontrado {
  opacity: 0.6;
}

.fomon-mapa__muestra {
  width: 14px;
  height: 4px;
  border-radius: var(--radius-pill);
}

.fomon-mapa__quitar {
  border: 0;
  background: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: 0 2px;
}

.fomon-mapa__panel small,
.fomon-mapa__resumen {
  color: var(--color-text-muted);
}

.fomon-mapa__aviso {
  position: absolute;
  bottom: 8px;
  left: 10px;
  margin: 0;
  padding: 4px 8px;
  font-size: 12px;
  border-radius: var(--radius-sm);
  background: var(--color-bg-surface);
  color: var(--color-accent-warning);
}
</style>
