// Nombre de archivo: herramientas.ts
// Ubicación de archivo: web/frontend/src/api/herramientas.ts
// Descripción: Cliente frontend de las herramientas auxiliares (comparación de VLANs)

import { request, requestJson } from './client';

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

export interface AlarmasCienaResultado {
  blob: Blob;
  formato: string;
  filas: string;
  columnas: string;
}

/** Convierte el CSV de alarmas Ciena a XLSX; los metadatos vienen en headers `X-*`. */
export async function procesarAlarmasCiena(archivo: File): Promise<AlarmasCienaResultado> {
  const formData = new FormData();
  formData.append('file', archivo);
  const response = await request('/api/tools/alarmas-ciena', { method: 'POST', formData, csrf: true });
  return {
    formato: response.headers.get('X-Formato-Detectado') ?? 'desconocido',
    filas: response.headers.get('X-Filas-Procesadas') ?? '?',
    columnas: response.headers.get('X-Columnas') ?? '?',
    blob: await response.blob(),
  };
}
