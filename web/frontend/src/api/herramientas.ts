// Nombre de archivo: herramientas.ts
// Ubicación de archivo: web/frontend/src/api/herramientas.ts
// Descripción: Cliente frontend de las herramientas auxiliares (comparación de VLANs)

import { requestJson } from './client';

export interface CompararVlansResponse {
  only_a?: number[];
  only_b?: number[];
  common?: number[];
  total_a?: number;
  total_b?: number;
}

export async function compararVlans(textA: string, textB: string): Promise<CompararVlansResponse> {
  return requestJson<CompararVlansResponse>('/api/tools/compare-vlans', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    json: { text_a: textA, text_b: textB },
  });
}
