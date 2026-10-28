// Nombre de archivo: infra.ts
// Ubicación de archivo: web/frontend/src/api/infra.ts
// Descripción: Cliente frontend de infraestructura FO (tracking de rutas, búsqueda de cámaras, baneos y carga de trackings)

import { requestDownload, requestJson } from './client';

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

export async function obtenerTrackingRuta(rutaId: number): Promise<TrackingDetailPayload> {
  return requestJson<TrackingDetailPayload>(`/api/infra/rutas/${rutaId}/tracking`, {
    headers: { Accept: 'application/json' },
  });
}

/**
 * Descarga el `.eml` del aviso de baneo. El endpoint (`EmlDownloadRequestModel`) espera JSON, no
 * multipart: `include_xls` / `include_txt` se omiten para que valgan sus defaults (true).
 */
export async function descargarEmlBaneo(body: {
  incident_id: number;
  recipients: string;
  subject: string;
  html_body: string;
}): Promise<string> {
  return requestDownload('/api/infra/notify/download-eml', {
    method: 'POST',
    json: body,
    fallbackFilename: `aviso_baneo_${body.incident_id}.eml`,
  });
}
