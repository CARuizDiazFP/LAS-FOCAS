// Nombre de archivo: foMonitor.ts
// Ubicación de archivo: web/frontend/src/api/foMonitor.ts
// Descripción: Cliente de /api/fo-monitor/* (intervenciones, GeoJSON del mapa, verificación manual, reconocimientos, config)

import { requestJson } from './client';

export type ColorSemaforo = 'VERDE' | 'AMARILLO' | 'NARANJA' | 'ROJO' | 'GRIS';
export type EstadoServicio = 'UP' | 'DOWN' | 'ADMIN_DOWN' | 'DESCONOCIDO' | 'NO_SOPORTADO';

export interface IntervencionResumen {
  id: number;
  origen: 'INGRESO' | 'MANUAL';
  estado: string;
  camara_id: number | null;
  camara: string | null;
  botella_objetivo_n_id: number | null;
  botella_objetivo: string | null;
  botella_1_inferida: boolean;
  cable_n_id_manual: number | null;
  tecnico: string | null;
  iniciada_por: string | null;
  fecha_ingreso: string | null;
  fecha_egreso: string | null;
  creada_at: string | null;
  cerrada_at: string | null;
  sin_linea_base: boolean;
  post_tardio: boolean;
  egreso_inferido: boolean;
  atribucion_compartida: boolean;
  color: ColorSemaforo | null;
  cables: number;
  servicios: number;
  caidas_nuevas: number;
}

export interface Medicion {
  estado: EstadoServicio;
  medido_at: string | null;
  extremo: string | null;
  motivo: string | null;
}

export interface ServicioCable {
  servicio_pk: number;
  servicio_id: string | null;
  tipo: string | null;
  categoria: number | null;
  cliente: string | null;
  reconocido: boolean;
  pre: Medicion | null;
  post: Medicion | null;
}

export interface CableDetalle {
  cable_n_id: number;
  nombre: string | null;
  clase: number | null;
  botella_n_id: number | null;
  es_objetivo: boolean;
  color: ColorSemaforo;
  motivo: string;
  fase: 'PRE' | 'POST';
  evaluables: number;
  conocidos: number;
  up: number;
  down: number;
  cobertura: number | null;
  caidas_nuevas: number[];
  recuperaciones: number[];
  servicios: ServicioCable[];
}

export interface ConsultaBurrito {
  id: number;
  fase: 'PRE' | 'POST' | 'REVERIF';
  intento: number;
  estado: string;
  ids: string[];
  permalink: string | null;
  ref: string | null;
  completa: boolean | null;
  enviada_at: string | null;
  respondida_at: string | null;
  error: string | null;
}

export interface Reconocimiento {
  id: number;
  servicio_pk: number | null;
  usuario: string;
  motivo: string;
  created_at: string | null;
}

export interface IntervencionDetalle extends IntervencionResumen {
  cables_detalle: CableDetalle[];
  consultas: ConsultaBurrito[];
  reconocimientos: Reconocimiento[];
}

export interface ListadoIntervenciones {
  total: number;
  limit: number;
  offset: number;
  items: IntervencionResumen[];
}

export interface FiltrosIntervenciones {
  estado?: string;
  tecnico?: string;
  cable?: string;
  limit?: number;
  offset?: number;
}

export interface MapaConfig {
  modo: 'local' | 'osm';
  pmtiles_url: string;
  glyphs_url: string;
  sprite_url: string;
  pmtiles_disponible: boolean;
}

export interface ConfigPiloto {
  activo: boolean;
  canal: string | null;
  ventana_desde: string | null;
  ventana_hasta: string | null;
  tope_mensajes_diario: number;
  max_ids_por_mensaje: number;
  timeout_base_s: number;
  timeout_por_servicio_s: number;
  concurrencia: number;
  prompt_version: string;
  canales_ingreso: string;
  mensajes_hoy: number;
  actualizado_por: string | null;
  actualizado_at: string | null;
}

export interface HistorialCable {
  cable_n_id: number;
  items: { intervencion_id: number; estado: string; creada_at: string | null; fecha_egreso: string | null;
    color: ColorSemaforo; up: number; evaluables: number }[];
}

function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : '';
}

export function listarIntervenciones(filtros: FiltrosIntervenciones, signal?: AbortSignal) {
  return requestJson<ListadoIntervenciones>(`/api/fo-monitor/intervenciones${query({ ...filtros })}`, { signal });
}

export function obtenerIntervencion(id: number, signal?: AbortSignal) {
  return requestJson<IntervencionDetalle>(`/api/fo-monitor/intervenciones/${id}`, { signal });
}

export function obtenerMapaIntervenciones(horas = 24, signal?: AbortSignal) {
  return requestJson<GeoJSON.FeatureCollection>(`/api/fo-monitor/mapa/intervenciones${query({ horas })}`, { signal });
}

export function obtenerMapaConfig() {
  return requestJson<MapaConfig>('/api/fo-monitor/mapa/config');
}

export function obtenerHistorialCable(cableNId: number) {
  return requestJson<HistorialCable>(`/api/fo-monitor/cables/${cableNId}/historial`);
}

export function crearVerificacionManual(cuerpo: { camara_id?: number; botella_n_id?: number; cable_n_id?: number }) {
  return requestJson<{ intervencion_id: number }>('/api/fo-monitor/verificaciones', {
    method: 'POST',
    json: cuerpo,
    csrf: true,
  });
}

export function reconocerComoAjena(intervencionId: number, motivo: string, servicioPk?: number) {
  return requestJson<{ id: number }>(`/api/fo-monitor/intervenciones/${intervencionId}/reconocimientos`, {
    method: 'POST',
    json: { motivo, servicio_pk: servicioPk ?? null },
    csrf: true,
  });
}

export function leerConfigPiloto() {
  return requestJson<ConfigPiloto>('/api/admin/fo-monitor/config');
}

export function actualizarConfigPiloto(cambios: Partial<ConfigPiloto>) {
  return requestJson<ConfigPiloto>('/api/admin/fo-monitor/config', { method: 'PUT', json: cambios, csrf: true });
}

export type TipoBusquedaMapa = 'servicio' | 'cable' | 'camara';

export interface ResultadoBusquedaMapa extends GeoJSON.FeatureCollection {
  meta: { tipo: TipoBusquedaMapa; q: string; encontrados: number; con_geometria: number; truncado: boolean };
}

export function buscarEnMapa(tipo: TipoBusquedaMapa, q: string) {
  const params = new URLSearchParams({ tipo, q });
  return requestJson<ResultadoBusquedaMapa>(`/api/fo-monitor/mapa/buscar?${params.toString()}`);
}

export interface ServicioResaltado {
  q: string;
  indice: number;
  encontrado: boolean;
  cables: number;
  servicio_pk?: number;
  servicio_id?: string;
  cliente?: string | null;
  tipo?: string | null;
  estado_servicio?: string | null;
  es_verificable?: boolean;
  cables_sin_trazado?: number;
}

export interface GeoServicios extends GeoJSON.FeatureCollection {
  servicios: ServicioResaltado[];
}

export function obtenerGeoServicios(ids: string[], signal?: AbortSignal) {
  return requestJson<GeoServicios>(`/api/fo-monitor/mapa/servicios?ids=${encodeURIComponent(ids.join(','))}`, { signal });
}

export interface ServicioEnFicha {
  servicio_pk: number;
  servicio_id: string | null;
  cliente: string | null;
  tipo: string | null;
  estado_servicio: string | null;
  categoria: number | null;
  es_verificable: boolean;
  pelos: number;
  ultimo: (Medicion & { fase: string; intervencion_id: number }) | null;
}

export interface FichaCable {
  cable_n_id: number;
  nombre: string | null;
  clase: number | null;
  capacidad: string | null;
  propietario: string | null;
  jerarquia: string | null;
  vigente: boolean;
  extremo_a: string | null;
  extremo_b: string | null;
  servicios: ServicioEnFicha[];
  verificables: number;
}

export function obtenerFichaCable(cableNId: number) {
  return requestJson<FichaCable>(`/api/fo-monitor/cables/${cableNId}/ficha`);
}
