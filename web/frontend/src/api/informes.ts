// Nombre de archivo: informes.ts
// Ubicación de archivo: web/frontend/src/api/informes.ts
// Descripción: Cliente frontend del historial de informes y de la generación de Repetitividad

import { request, requestJson } from './client';

export interface ReportHistoryItem {
  id: number;
  report_type: string;
  status: string;
  username: string;
  source: string;
  period_month: number;
  period_year: number;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  input_metadata: Record<string, unknown>;
  output_metadata: {
    outputs?: Record<string, string | string[]>;
    stats?: Record<string, unknown>;
  };
  error_code: string | null;
  error_message: string | null;
}

export interface ReportsHistoryResponse {
  items?: ReportHistoryItem[];
}

/** `query` es el query string ya armado, sin el `?` (puede ser vacío). */
export async function listarHistorialInformes(query: string): Promise<ReportsHistoryResponse> {
  return requestJson<ReportsHistoryResponse>(`/api/reports/history${query ? `?${query}` : ''}`);
}

export async function getUltimoReporte(tipo: 'sla' | 'repetitividad'): Promise<ReportsHistoryResponse> {
  return requestJson<ReportsHistoryResponse>(`/api/reports/history?type=${tipo}&limit=1`);
}

export interface RepetitividadResponse {
  docx?: string;
  pdf?: string;
  pdf_error?: string;
  map_images?: string[];
}

export async function generarRepetitividad(data: FormData): Promise<RepetitividadResponse> {
  return requestJson<RepetitividadResponse>('/api/flows/repetitividad', { method: 'POST', formData: data });
}

/** Resultado de un informe que se interpreta con el status HTTP y el cuerpo (sin lanzar por no-2xx). */
export interface ResultadoInforme<T> {
  ok: boolean;
  status: number;
  data: T;
}

async function postInforme<T>(url: string, formData: FormData): Promise<ResultadoInforme<T>> {
  const response = await request(url, { method: 'POST', formData, csrf: true, throwOnError: false });
  const data = (await response.json().catch(() => ({}))) as T;
  return { ok: response.ok, status: response.status, data };
}

/** Informe SLA. El llamador decide el error según `ok`/`status`/`data` (no lanza por no-2xx). */
export async function generarInformeSla<T>(formData: FormData): Promise<ResultadoInforme<T>> {
  return postInforme<T>('/api/reports/sla', formData);
}

/** Informe SLA consumido. Mismo contrato que `generarInformeSla`. */
export async function generarInformeSlaConsumo<T>(formData: FormData): Promise<ResultadoInforme<T>> {
  return postInforme<T>('/api/reports/sla-consumo', formData);
}
