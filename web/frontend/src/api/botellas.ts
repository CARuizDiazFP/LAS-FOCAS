// Nombre de archivo: botellas.ts
// Ubicación de archivo: web/frontend/src/api/botellas.ts
// Descripción: Cliente frontend para el listado unificado de Botellas (Cromo + legado Infra/Baneos)

import { requestJson } from './client';

export type BotellaOrigen = 'cromo' | 'legado';

export interface BotellaUnificadaItem {
  origen: BotellaOrigen;
  id: number;
  nombre: string | null;
  estado: string | null;
}

export interface SearchBotellasResponse {
  total: number;
  limit: number;
  offset: number;
  botellas: BotellaUnificadaItem[];
}

export interface SearchBotellasParams {
  q?: string;
  limit?: number;
  offset?: number;
}

export type EstadoBotellaToken = 'ok' | 'warn' | 'error' | 'idle';

export function estadoBotellaToken(estado: string | null | undefined): EstadoBotellaToken {
  const value = (estado ?? '').trim().toUpperCase();
  if (value === 'LIBRE') return 'ok';
  if (value === 'OCUPADA') return 'warn';
  if (value === 'BANEADA') return 'error';
  return 'idle';
}

function toQuery(params: SearchBotellasParams): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function searchBotellas(params: SearchBotellasParams): Promise<SearchBotellasResponse> {
  return requestJson<SearchBotellasResponse>(`/api/infra/botellas/buscar${toQuery(params)}`);
}
