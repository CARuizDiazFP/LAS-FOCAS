// Nombre de archivo: servicios.ts
// Ubicación de archivo: web/frontend/src/api/servicios.ts
// Descripción: Cliente frontend para ingesta y búsqueda paginada del módulo servicios

import { ApiError, getCsrfToken, requestJson } from './client';

export interface IngestServiciosResponse {
  status: string;
  rows_ok: number;
  rows_bad: number;
  inserted: number;
  updated: number;
  unchanged: number;
}

export interface ServicioItem {
  id: number;
  numero_primer_servicio: string;
  nombre_cliente: string | null;
  numero_linea: string | null;
  tipo_servicio: string | null;
  sla_prometido: string | null;
  direccion: string | null;
  localidad: string | null;
  provincia: string | null;
  direccion_2: string | null;
  estado_servicio: string;
  categoria: number;
  origen_datos: string;
  reclamos: Array<Record<string, unknown>> | null;
}

export interface SearchServiciosResponse {
  status: string;
  total: number;
  limit: number;
  offset: number;
  servicios: ServicioItem[];
}

export interface ServicioDetailResponse {
  status: string;
  id_consultado: string;
  id_origen: string;
  servicio: ServicioItem;
}

export interface SearchServiciosParams {
  q?: string;
  numero_primer_servicio?: string;
  cliente?: string;
  domicilio?: string;
  tipo?: string;
  estado?: string;
  categoria?: string;
  limit?: number;
  offset?: number;
}

/** Categorías admisibles (C0 = máxima prioridad, C6 = sin clasificar / default). */
export const CATEGORIAS_SERVICIO = [0, 1, 2, 3, 4, 5, 6] as const;
export type CategoriaServicio = (typeof CATEGORIAS_SERVICIO)[number];

export function categoriaLabel(categoria: number): string {
  return `C${categoria}`;
}

export type EstadoServicioToken = 'ok' | 'warn' | 'error' | 'idle';

export function estadoServicioToken(estado: string | null | undefined): EstadoServicioToken {
  const value = (estado ?? '').trim().toLowerCase();
  if (value === 'activo') return 'ok';
  if (['observado', 'en observación', 'degradado'].includes(value)) return 'warn';
  if (['baja', 'dado de baja', 'inactivo'].includes(value)) return 'error';
  return 'idle';
}

function toQuery(params: SearchServiciosParams): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function searchServicios(params: SearchServiciosParams): Promise<SearchServiciosResponse> {
  return requestJson<SearchServiciosResponse>(`/api/servicios/search${toQuery(params)}`);
}

export async function getServicioDetail(id: string): Promise<ServicioDetailResponse> {
  const clean = id.trim();
  const query = new URLSearchParams({ id: clean }).toString();
  return requestJson<ServicioDetailResponse>(`/api/servicios/detail?${query}`);
}

export function ingestServiciosFile(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<IngestServiciosResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/servicios/ingest', true);
    xhr.withCredentials = true;

    xhr.upload.onprogress = (event: ProgressEvent<EventTarget>) => {
      if (!event.lengthComputable || !onProgress) return;
      const percent = Math.min(100, Math.round((event.loaded / event.total) * 100));
      onProgress(percent);
    };

    xhr.onload = () => {
      let payload: unknown = null;
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        payload = null;
      }

      if (xhr.status >= 200 && xhr.status < 300 && payload && typeof payload === 'object') {
        resolve(payload as IngestServiciosResponse);
        return;
      }

      const message =
        payload && typeof payload === 'object' && 'error' in payload && typeof (payload as { error?: unknown }).error === 'string'
          ? String((payload as { error?: unknown }).error)
          : `Error ${xhr.status}`;

      reject(new ApiError(message, xhr.status || 500, payload));
    };

    xhr.onerror = () => {
      reject(new ApiError('No se pudo completar la subida del archivo', 0));
    };

    const data = new FormData();
    data.append('file', file, file.name);
    data.append('csrf_token', getCsrfToken());
    xhr.send(data);
  });
}

/** Cambia la categoría (C0-C6) de un Servicio individual — sólo admin. Devuelve el item actualizado
 * para refrescar la vista sin recargar. Ver `PATCH /api/servicios/{id}/categoria`. */
export async function updateServicioCategoria(id: number, categoria: number): Promise<ServicioItem> {
  return requestJson<ServicioItem>(`/api/servicios/${id}/categoria`, {
    method: 'PATCH',
    json: { categoria },
    csrf: true,
  });
}

export interface ServiciosCategoriaMasivaResponse {
  status: string;
  categoria_nueva: number;
  actualizados: number;
  no_encontrados: number[];
}

/** Cambia la categoría (C0-C6) de un lote de Servicios en una sola operación — sólo admin. Ver
 * `PATCH /api/servicios/bulk-categoria`. */
export async function updateServiciosCategoriaMasivo(
  servicioIds: number[],
  categoria: number,
): Promise<ServiciosCategoriaMasivaResponse> {
  return requestJson<ServiciosCategoriaMasivaResponse>('/api/servicios/bulk-categoria', {
    method: 'PATCH',
    json: { servicio_ids: servicioIds, categoria },
    csrf: true,
  });
}
