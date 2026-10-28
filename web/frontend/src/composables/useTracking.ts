// Nombre de archivo: useTracking.ts
// Ubicación de archivo: web/frontend/src/composables/useTracking.ts
// Descripción: Utilidades reutilizables para consultar y descargar tracking de rutas FO en el panel web

import { ApiError, requestDownload } from '../api/client';
import { obtenerTrackingRuta, type TrackingDetailPayload } from '../api/infra';

export type { TrackingEntry, TrackingPointInfo, TrackingDetailPayload } from '../api/infra';

export async function loadTrackingDetail(rutaId: number): Promise<TrackingDetailPayload> {
  return obtenerTrackingRuta(rutaId);
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