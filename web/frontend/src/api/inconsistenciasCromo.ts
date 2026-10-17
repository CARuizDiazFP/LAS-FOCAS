// Nombre de archivo: inconsistenciasCromo.ts
// Ubicación de archivo: web/frontend/src/api/inconsistenciasCromo.ts
// Descripción: Cliente frontend de las inconsistencias de Cromo — listado paginado con filtros, cambio de estado en lote (cuarentena, aceptar, reportar, liberar) y detección manual (corrida del cromo_worker)

import { requestDownload, requestJson } from './client';

// Mismos literales que `core/services/cromo/inconsistencias_cromo.py` y los CHECK de
// `app.cromo_inconsistencia`.
export const TIPOS_INCONSISTENCIA = ['ISLA_FUSION', 'CABLE_SIN_EXTREMO', 'ELEMENTO_ISLA'] as const;
export type TipoInconsistencia = (typeof TIPOS_INCONSISTENCIA)[number];

export const ESTADOS_INCONSISTENCIA = [
  'PENDIENTE',
  'CUARENTENA',
  'REPORTADA',
  'CORREGIDA',
  'ACEPTADA',
] as const;
export type EstadoInconsistencia = (typeof ESTADOS_INCONSISTENCIA)[number];

/** Estados a los que una persona puede mover un caso (liberar = PENDIENTE). */
export type EstadoDestinoInconsistencia = 'CUARENTENA' | 'ACEPTADA' | 'REPORTADA' | 'PENDIENTE';

const TIPO_LABELS: Record<TipoInconsistencia, string> = {
  ISLA_FUSION: 'Isla de fusión',
  CABLE_SIN_EXTREMO: 'Cable sin extremo',
  ELEMENTO_ISLA: 'Elemento isla',
};

export function tipoInconsistenciaLabel(tipo: string): string {
  return TIPO_LABELS[tipo as TipoInconsistencia] ?? tipo;
}

export interface EvidenciaInconsistencia {
  motivo?: string;
  contenedor?: { nombre?: string | null; es_odf?: boolean };
  cables?: { n_id?: number; nombre?: string | null }[];
  servicios?: string[];
  pelos_en_uso?: number;
  elemento_conocido?: string | null;
}

export interface InconsistenciaItem {
  id: number;
  tipo: string;
  objeto_n_id: number;
  objeto_clase: number | null;
  nombre: string | null;
  localidad: string | null;
  revision: string;
  estado: string;
  evidencia: EvidenciaInconsistencia;
  primera_vez: string | null;
  ultima_vez: string | null;
  actualizado_por: string | null;
  actualizado_en: string | null;
  pelos: number;
  servicios: number;
}

export interface ListadoInconsistenciasResponse {
  total: number;
  por_pagina: number;
  desplazamiento: number;
  items: InconsistenciaItem[];
  /** Con todos los filtros salvo el de tipo (para los chips). */
  conteos_por_tipo: Record<string, number>;
}

export interface ListarInconsistenciasParams {
  tipo?: string;
  estado?: string;
  revision?: string;
  localidad?: string;
  servicio?: string;
  servicio_id?: number;
  limit?: number;
  offset?: number;
}

function toQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

const BASE = '/api/admin/infra/inconsistencias-cromo';

export async function listarInconsistencias(
  params: ListarInconsistenciasParams,
): Promise<ListadoInconsistenciasResponse> {
  return requestJson<ListadoInconsistenciasResponse>(`${BASE}${toQuery({ ...params })}`);
}

export interface ResultadoCambioEstado {
  ok: boolean;
  aplicados: number[];
  rechazados: { id: number; motivo: string }[];
}

export async function cambiarEstadoInconsistencias(
  ids: number[],
  estado: EstadoDestinoInconsistencia,
): Promise<ResultadoCambioEstado> {
  return requestJson<ResultadoCambioEstado>(`${BASE}/estado`, {
    method: 'POST',
    json: { ids, estado },
    csrf: true,
  });
}

// ── Detección manual (corrida sintética del cromo_worker) ─────────────────

export interface CorridaDeteccion {
  id: number;
  estado: string;
  total_objetivo: number | null;
  leidas: number;
  errores: number;
  iniciada_at: string | null;
  finalizada_at: string | null;
}

export interface EstadoDeteccion {
  corrida: CorridaDeteccion | null;
}

export async function obtenerDeteccion(): Promise<EstadoDeteccion> {
  return requestJson<EstadoDeteccion>(`${BASE}/deteccion`);
}

export async function lanzarDeteccion(): Promise<{ corrida_id: number }> {
  return requestJson(`${BASE}/deteccion`, { method: 'POST', json: {}, csrf: true });
}

/** Descarga el XLSX "para corregir en Cromo" (una hoja por localidad) con los mismos filtros del listado. */
export async function exportarInconsistencias(
  params: Omit<ListarInconsistenciasParams, 'limit' | 'offset'>,
): Promise<string> {
  return requestDownload(`${BASE}/exportar.xlsx${toQuery({ ...params })}`, {
    fallbackFilename: 'inconsistencias_cromo.xlsx',
  });
}
