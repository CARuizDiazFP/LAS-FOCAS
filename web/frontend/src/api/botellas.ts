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
  incluirNoOperativas?: boolean;
}

const PARAM_KEY_MAP: Record<string, string> = { incluirNoOperativas: 'incluir_no_operativas' };

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
    // `false` se omite a propósito además de undefined/null/'': el default del backend ya es
    // `incluir_no_operativas=false`, no hace falta viajarlo cuando el toggle está apagado.
    if (value === undefined || value === null || value === '' || value === false) return;
    query.set(PARAM_KEY_MAP[key] ?? key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function searchBotellas(params: SearchBotellasParams): Promise<SearchBotellasResponse> {
  return requestJson<SearchBotellasResponse>(`/api/infra/botellas/buscar${toQuery(params)}`);
}
