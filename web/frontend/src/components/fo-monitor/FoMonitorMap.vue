<!--
  Nombre de archivo: FoMonitorMap.vue
  Ubicación de archivo: web/frontend/src/components/fo-monitor/FoMonitorMap.vue
  Descripción: Mapa MapLibre de FO Monitor — red FO en gris, cables de intervenciones por color de semáforo y botellas
-->
<template>
  <div class="fomon-mapa">
    <div ref="contenedor" class="fomon-mapa__lienzo" role="region" aria-label="Mapa de cables FO"></div>
    <div class="fomon-mapa__capas card">
      <label><input v-model="verRed" type="checkbox" /> Red FO completa</label>
      <label><input v-model="verBotellas" type="checkbox" /> Botellas (zoom ≥ 15)</label>
    </div>
    <p v-if="avisoBase" class="fomon-mapa__aviso">{{ avisoBase }}</p>
  </div>
</template>

<script setup lang="ts">
import * as maplibregl from 'maplibre-gl';
import type { GeoJSONSource, StyleSpecification } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { layers, namedFlavor } from '@protomaps/basemaps';
import { Protocol } from 'pmtiles';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { obtenerMapaConfig, type ColorSemaforo, type MapaConfig } from '../../api/foMonitor';
import { requestJson } from '../../api/client';
import { paletaSemaforo, resolverToken } from './colores';

const props = defineProps<{
  intervenciones: GeoJSON.FeatureCollection | null;
  cableSeleccionado: number | null;
}>();
const emit = defineEmits<{ (e: 'seleccionar', payload: { cableNId: number; intervencionId: number | null }): void }>();

const contenedor = ref<HTMLDivElement | null>(null);
const verRed = ref(true);
const verBotellas = ref(false);
const avisoBase = ref('');
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
  const red = await requestJson<GeoJSON.FeatureCollection>('/api/fo-monitor/mapa/red');
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
  const datos = await requestJson<GeoJSON.FeatureCollection>(`/api/fo-monitor/mapa/botellas?bbox=${bbox}`);
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
  protocolo = new Protocol();
  maplibregl.addProtocol('pmtiles', protocolo.tile);
  mapa = new maplibregl.Map({ container: contenedor.value, style: estiloBase(cfg), center: CENTRO_AMBA, zoom: 11, attributionControl: { compact: true } });
  mapa.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');

  mapa.on('load', () => {
    if (!mapa) return;
    const paleta = paletaSemaforo();
    mapa.addSource('interv', { type: 'geojson', data: props.intervenciones ?? VACIO });
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
    void cargarRed();
    mapa.on('click', 'interv-linea', (ev) => {
      const p = ev.features?.[0]?.properties;
      if (p) emit('seleccionar', { cableNId: Number(p.cable_n_id), intervencionId: Number(p.intervencion_id) });
    });
    mapa.on('click', 'red-linea', (ev) => {
      if (mapa?.queryRenderedFeatures(ev.point, { layers: ['interv-linea'] }).length) return;
      const p = ev.features?.[0]?.properties;
      if (p) emit('seleccionar', { cableNId: Number(p.id), intervencionId: null });
    });
    for (const capa of ['interv-linea', 'red-linea']) {
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
});
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

.fomon-mapa__capas {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 10px;
  font-size: 12px;
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
