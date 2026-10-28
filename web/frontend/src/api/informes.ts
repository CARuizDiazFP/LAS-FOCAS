// Nombre de archivo: informes.ts
// Ubicación de archivo: web/frontend/src/api/informes.ts
// Descripción: Cliente frontend del historial de informes y de la generación de Repetitividad

import { requestJson } from './client';

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
