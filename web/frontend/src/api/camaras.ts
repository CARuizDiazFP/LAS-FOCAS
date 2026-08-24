// Nombre de archivo: camaras.ts
// Ubicación de archivo: web/frontend/src/api/camaras.ts
// Descripción: Cliente frontend para la ingesta masiva de cámaras, el listado del dashboard Viewer y la detección de duplicados

import { ApiError, getCsrfToken, requestJson } from './client';

export interface CamaraViewerItem {
  id: number;
  nombre: string;
  estado: string;
  botellas_count: number;
  cables_count: number;
}

export interface SearchCamarasViewerResponse {
  total: number;
  limit: number;
  offset: number;
  camaras: CamaraViewerItem[];
}

export interface SearchCamarasViewerParams {
  q?: string;
  estado?: string;
  limit?: number;
  offset?: number;
}

function toQuery(params: SearchCamarasViewerParams): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function searchCamarasViewer(params: SearchCamarasViewerParams): Promise<SearchCamarasViewerResponse> {
  return requestJson<SearchCamarasViewerResponse>(`/api/admin/infra/camaras/viewer${toQuery(params)}`);
}

export interface GrupoCamarasDuplicadas {
  clave_normalizada: string;
  criterio: string;
  estados_en_conflicto: boolean;
  estado_mas_restrictivo: string;
  miembros: CamaraViewerItem[];
}

export interface CamarasDuplicadosResponse {
  total_grupos: number;
  grupos: GrupoCamarasDuplicadas[];
}

export async function getCamarasDuplicados(): Promise<CamarasDuplicadosResponse> {
  return requestJson<CamarasDuplicadosResponse>('/api/admin/infra/camaras/viewer/duplicados');
}

export interface MergeMasivoDetalleItem {
  exito: boolean;
  principal_id: number;
  secundarias_fusionadas?: number[];
  secundaria_ids?: number[];
  estado_final?: string;
  error?: string;
}

export interface MergeMasivoResponse {
  ok: boolean;
  total_grupos: number;
  grupos_fusionados: number;
  grupos_con_error: number;
  detalle: MergeMasivoDetalleItem[];
}

/** Fusiona automáticamente TODOS los grupos de Cámaras duplicadas detectados — cada grupo elige su
 * propia principal (más botellas+cables, empate id más bajo) y corre en su propia transacción. */
export async function mergeMasivoCamaras(guardarAlias = true): Promise<MergeMasivoResponse> {
  return requestJson<MergeMasivoResponse>('/api/infra/camaras/merge-masivo', {
    method: 'POST',
    json: { guardar_alias: guardarAlias },
    csrf: true,
  });
}

export type EstadoCamaraToken = 'ok' | 'warn' | 'error' | 'idle';

export function estadoCamaraToken(estado: string | null | undefined): EstadoCamaraToken {
  const value = (estado ?? '').trim().toUpperCase();
  if (value === 'LIBRE') return 'ok';
  if (value === 'OCUPADA') return 'warn';
  if (value === 'BANEADA') return 'error';
  return 'idle';
}

export interface NombreSinMatch {
  caso_id: number;
  nombre: string;
}

export interface IngestCamarasResponse {
  status: string;
  total_leidos: number;
  grupos_baneados: number;
  grupos_ya_baneados: number;
  sin_match: NombreSinMatch[];
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

// ── Eliminación permanente de una Cámara raíz genuinamente vacía ────────────
// Todo o nada: si la Cámara o cualquiera de sus Botellas tiene Cables/Empalmes/Ingresos/Fusiones
// reales asociados, se rechaza sin borrar nada. Cada Botella Cromo eliminada registra su n_id en
// app.cromo_botella_alias (accion='ignorar'). Ver POST /api/infra/camaras/eliminar.

export interface BloqueoEliminacion {
  origen: 'legado' | 'cromo' | 'camara';
  id: number;
  nombre: string | null;
  razon: string;
}

export interface EliminarCamaraResponse {
  ok: boolean;
  camara_id: number;
  botellas_legado_eliminadas: number;
  botellas_cromo_eliminadas: number;
  aliases_registrados: number;
}

export async function eliminarCamara(camaraId: number): Promise<EliminarCamaraResponse> {
  return requestJson<EliminarCamaraResponse>('/api/infra/camaras/eliminar', {
    method: 'POST',
    json: { camara_id: camaraId },
    csrf: true,
  });
}

// ── Asociación manual de nombres sin match (ingesta Excel) a una Cámara/Botella existente ──

export interface ConflictoAsociacionSinMatch {
  caso_id: number;
  nombre: string;
  camara_actual_id: number;
  camara_actual_nombre: string;
}

export interface AsociarSinMatchResponse {
  ok: boolean;
  camara_id: number;
  camara_nombre: string;
  estado_final: string;
  baneo_aplicado: boolean;
  alias_creados: number;
  alias_preexistentes: number;
  casos_marcados: number;
  conflictos: ConflictoAsociacionSinMatch[];
  error: string | null;
}

export async function asociarSinMatchCamaras(
  casoIds: number[],
  camaraId: number,
  motivo?: string,
): Promise<AsociarSinMatchResponse> {
  return requestJson<AsociarSinMatchResponse>('/api/admin/ingesta/camaras/asociar', {
    method: 'POST',
    json: { caso_ids: casoIds, camara_id: camaraId, motivo: motivo ?? null },
    csrf: true,
  });
}
