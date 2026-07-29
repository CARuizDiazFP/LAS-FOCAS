// Nombre de archivo: camaras.ts
// Ubicación de archivo: web/frontend/src/api/camaras.ts
// Descripción: Cliente frontend para la ingesta masiva de cámaras con baneo administrativo

import { ApiError, getCsrfToken } from './client';

export interface IngestCamarasResponse {
  status: string;
  creadas: number;
  preexistentes: number;
  baneadas: number;
  errores: string[];
}

export function ingestCamarasFile(
  file: File,
  motivoBaneo: string,
  onProgress?: (percent: number) => void,
): Promise<IngestCamarasResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/admin/ingesta/camaras', true);
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
        resolve(payload as IngestCamarasResponse);
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
    data.append('motivo_baneo', motivoBaneo);
    xhr.send(data);
  });
}
