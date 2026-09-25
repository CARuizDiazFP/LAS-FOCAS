// Nombre de archivo: useTracking.ts
// Ubicación de archivo: web/frontend/src/composables/useTracking.ts
// Descripción: Utilidades reutilizables para consultar y descargar tracking de rutas FO en el panel web

import { ApiError, requestDownload } from '../api/client';

export interface TrackingPointInfo {
  sitio: string;
  identificador: string;
  conector: string;
}

export interface TrackingEntry {
  tipo: 'camara' | 'cable' | string;
  descripcion?: string;
  empalme_id?: number | null;
  nombre?: string;
  atenuacion_db?: number | null;
}

export interface TrackingDetailPayload {
  status: string;
  ruta_id: number;
  servicio_id: string;
  ruta_nombre: string;
  ruta_tipo: string;
  tracking: TrackingEntry[];
  punta_a: TrackingPointInfo | null;
  punta_b: TrackingPointInfo | null;
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const data = await response.json() as T & { error?: string };
  if (!response.ok) {
    throw new Error(data.error ?? `Error ${response.status}`);
  }
  return data;
}

export async function loadTrackingDetail(rutaId: number): Promise<TrackingDetailPayload> {
  const response = await fetch(`/api/infra/rutas/${rutaId}/tracking`, {
    credentials: 'include',
    headers: { Accept: 'application/json' },
  });
  return parseJsonResponse<TrackingDetailPayload>(response);
}

/**
 * Descarga el `.txt` ORIGINAL de una ruta legacy (el que se subió a mano).
 *
 * Envuelve `requestDownload` de `api/client.ts` en vez de repetir el patrón
 * blob+anchor+revoke. Se preserva textual el mensaje de 404, que es específico de este dominio:
 * un 404 acá significa que esa ruta no tiene `raw_file_content`, no que la ruta no exista.
 */
export async function downloadTracking(rutaId: number): Promise<string> {
  try {
    return await requestDownload(`/api/infra/tracking/${rutaId}/download`, {
      fallbackFilename: `tracking_ruta_${rutaId}.txt`,
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      throw new Error('El TXT original no está disponible para esta ruta.');
    }
    throw error;
  }
}