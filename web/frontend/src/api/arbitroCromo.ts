// Nombre de archivo: arbitroCromo.ts
// Ubicación de archivo: web/frontend/src/api/arbitroCromo.ts
// Descripción: Cliente frontend del árbitro de Cromo — propuestas (listar, aplicar, rechazar, revertir), reglas, análisis retroactivo y su historial de evaluaciones

import { ApiError, requestJson } from './client';

export const MODOS_REGLA = ['APAGADA', 'SOMBRA', 'AUTO'] as const;
export type ModoRegla = (typeof MODOS_REGLA)[number];

export interface SenalArbitro {
  codigo: string;
  peso: number;
  /** Objeto JSON con el detalle de la señal (p. ej. `{"odf_n_id": 123}`). */
  detalle?: Record<string, unknown> | null;
  veto?: boolean;
}

export interface PropuestaArbitro {
  id: number;
  regla: string;
  objeto_tipo: string;
  objeto_id: number;
  accion: string;
  parametros: Record<string, unknown>;
  confianza: number;
  senales: SenalArbitro[];
  estado: string;
  disparo: string;
  modo_al_evaluar: string;
  nota: string | null;
  creada_en: string | null;
  actualizada_en: string | null;
  decidida_por: string | null;
}

export interface ListarPropuestasParams {
  regla?: string;
  estado?: string;
  limit?: number;
  offset?: number;
}

export interface ListadoPropuestasResponse {
  items: PropuestaArbitro[];
  total: number;
}

export interface ReglaArbitro {
  codigo: string;
  descripcion: string;
  modo: string;
  umbral: number;
  presupuesto_por_corrida: number;
  aceptadas: number;
  rechazadas: number;
  decididas: number;
  precision: number | null;
  sugerir_auto: boolean;
}

export interface ResumenReglaEvaluacion {
  nuevas?: number;
  actualizadas?: number;
  obsoletas?: number;
  aplicadas_auto?: number;
  confirmadas?: number;
  revertidas?: number;
  presupuesto_excedido?: number;
  error?: string;
}

export interface EvaluacionArbitro {
  id: number;
  disparo: string;
  alcance: unknown;
  reglas: string[] | null;
  estado: string;
  resumen: { por_regla?: Record<string, ResumenReglaEvaluacion> } | null;
  error: string | null;
  solicitada_por: string | null;
  encolada_en: string | null;
  iniciada_en: string | null;
  terminada_en: string | null;
}

export interface ListadoEvaluacionesResponse {
  items: EvaluacionArbitro[];
  en_curso: number | null;
}

export interface ResultadoAplicar {
  ok: boolean;
  aplicados: number[];
  rechazados: { id: number; motivo: string }[];
}
export interface ResultadoRechazar {
  ok: boolean;
  rechazados: number[];
  omitidos: { id: number; motivo: string }[];
}
export interface ResultadoRevertir {
  ok: boolean;
  revertidos: number[];
  omitidos: { id: number; motivo: string }[];
}

const BASE = '/api/admin/infra/arbitro-cromo';

function toQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export function listarPropuestas(params: ListarPropuestasParams): Promise<ListadoPropuestasResponse> {
  return requestJson<ListadoPropuestasResponse>(`${BASE}/propuestas${toQuery({ ...params })}`);
}

export function aplicarPropuestas(ids: number[]): Promise<ResultadoAplicar> {
  return requestJson<ResultadoAplicar>(`${BASE}/propuestas/aplicar`, { method: 'POST', json: { ids }, csrf: true });
}

export function rechazarPropuestas(ids: number[]): Promise<ResultadoRechazar> {
  return requestJson<ResultadoRechazar>(`${BASE}/propuestas/rechazar`, { method: 'POST', json: { ids }, csrf: true });
}

export function revertirPropuestas(ids: number[]): Promise<ResultadoRevertir> {
  return requestJson<ResultadoRevertir>(`${BASE}/propuestas/revertir`, { method: 'POST', json: { ids }, csrf: true });
}

export async function listarReglas(): Promise<ReglaArbitro[]> {
  const respuesta = await requestJson<{ reglas: ReglaArbitro[] }>(`${BASE}/reglas`);
  return respuesta.reglas;
}

export function actualizarRegla(
  codigo: string,
  cambios: { modo: string; umbral: number; presupuesto_por_corrida: number },
): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>(`${BASE}/reglas`, { method: 'POST', json: { codigo, ...cambios }, csrf: true });
}

/** 202 con el id de la evaluación; 409 (ya hay una en curso) y 503 (no se pudo encolar) llegan como `ApiError`. */
export function ejecutarAnalisisRetroactivo(reglas?: string[]): Promise<{ evaluacion_id: number }> {
  return requestJson<{ evaluacion_id: number }>(`${BASE}/normalizar`, {
    method: 'POST',
    json: { reglas: reglas ?? [] },
    csrf: true,
  });
}

export function listarEvaluaciones(limit = 10): Promise<ListadoEvaluacionesResponse> {
  return requestJson<ListadoEvaluacionesResponse>(`${BASE}/evaluaciones${toQuery({ limit })}`);
}

/** Id de la evaluación que el backend informa en un 409/503 (para seguir la que ya corre), si viene. */
export function evaluacionIdDeError(err: unknown): number | null {
  if (!(err instanceof ApiError)) return null;
  const payload = err.payload as { evaluacion_id?: unknown } | null | undefined;
  return typeof payload?.evaluacion_id === 'number' ? payload.evaluacion_id : null;
}
