// Nombre de archivo: infra.ts
// Ubicación de archivo: web/frontend/src/api/infra.ts
// Descripción: Cliente frontend de infraestructura FO (tracking de rutas)

import { requestJson } from './client';
import type { TrackingDetailPayload } from '../composables/useTracking';

export async function obtenerTrackingRuta(rutaId: number): Promise<TrackingDetailPayload> {
  return requestJson<TrackingDetailPayload>(`/api/infra/rutas/${rutaId}/tracking`, {
    headers: { Accept: 'application/json' },
  });
}
