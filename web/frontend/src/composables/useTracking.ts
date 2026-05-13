// Nombre de archivo: useTracking.ts
// Ubicación de archivo: web/frontend/src/composables/useTracking.ts
// Descripción: Utilidades reutilizables para consultar y descargar tracking de rutas FO en el panel web

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

export async function downloadTracking(rutaId: number): Promise<string> {
  const response = await fetch(`/api/infra/tracking/${rutaId}/download`, {
    credentials: 'include',
    headers: { Accept: 'text/plain, application/octet-stream' },
  });

  if (response.status === 404) {
    throw new Error('El TXT original no está disponible para esta ruta.');
  }
  if (!response.ok) {
    throw new Error(`Error ${response.status}`);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const match = disposition.match(/filename="(.+?)"/);
  const filename = match ? match[1] : `tracking_ruta_${rutaId}.txt`;
  const blobUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');

  anchor.href = blobUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(blobUrl);

  return filename;
}