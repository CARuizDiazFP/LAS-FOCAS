// Nombre de archivo: camaras.ts
// Ubicación de archivo: web/frontend/src/api/camaras.ts
// Descripción: Cliente frontend para la ingesta masiva de cámaras, el listado del dashboard Viewer y la detección de duplicados

import { ApiError, CSRF_HEADER, getCsrfToken, requestJson } from './client';
import type { BotellaOrigen } from './botellas';

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
    xhr.setRequestHeader(CSRF_HEADER, getCsrfToken());

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

// ── Selectores livianos de destino (mover un ingreso a otra Cámara) ──────────

export interface CamaraCandidata {
  id: number;
  nombre: string;
  direccion: string | null;
  estado: string;
  botellas_count: number;
  cables_count: number;
}

/**
 * Búsqueda liviana de Cámaras **raíz** por nombre (`GET /api/infra/camaras/buscar`, `solo_raiz`
 * explícito aunque es el default del backend). `signal` permite descartar una búsqueda vieja cuando
 * el usuario sigue tipeando.
 */
export async function buscarCamarasRaiz(
  q: string,
  options: { limit?: number; excluirId?: number | null; signal?: AbortSignal } = {},
): Promise<CamaraCandidata[]> {
  const params = new URLSearchParams({ q, limit: String(options.limit ?? 10), solo_raiz: 'true' });
  if (options.excluirId != null) params.set('excluir_id', String(options.excluirId));
  const data = await requestJson<{ camaras?: CamaraCandidata[] }>(`/api/infra/camaras/buscar?${params}`, {
    signal: options.signal,
  });
  return data.camaras ?? [];
}

export interface BotellaCromoHija {
  origen: 'cromo';
  /** `n_id` de la CromoBotella. */
  id: number;
  nombre: string | null;
  estado: string | null;
}

/**
 * Botellas Cromo (vigentes: el backend ya filtra `vigente`) que cuelgan de una Cámara
 * (`GET /api/infra/camaras/{id}/botellas`, que también trae las legado: se descartan acá).
 */
export async function getBotellasCromoDeCamara(
  camaraId: number,
  signal?: AbortSignal,
): Promise<BotellaCromoHija[]> {
  const data = await requestJson<{ botellas?: Array<{ origen: string; id: number; nombre: string | null; estado: string | null }> }>(
    `/api/infra/camaras/${camaraId}/botellas`,
    { signal },
  );
  return (data.botellas ?? [])
    .filter((botella) => botella.origen === 'cromo')
    .map((botella) => ({ origen: 'cromo' as const, id: botella.id, nombre: botella.nombre, estado: botella.estado }));
}

// ── Búsqueda de Cámaras y operaciones usadas por modales y vistas de detalle ──

/** Candidata devuelta por `GET /api/infra/camaras/buscar`; los campos de Botella aparecen sólo con `solo_raiz=false`. */
export interface CamaraBuscada extends CamaraCandidata {
  es_botella?: boolean;
  camara_padre_id?: number | null;
  camara_padre_nombre?: string | null;
}

/** Búsqueda liviana de Cámaras (`q`, `limit`, `excluir_id`, `solo_raiz`); devuelve la lista ya desempaquetada. */
export async function buscarCamaras(params: URLSearchParams): Promise<CamaraBuscada[]> {
  const data = await requestJson<{ camaras?: CamaraBuscada[] }>(`/api/infra/camaras/buscar?${params}`);
  return data.camaras ?? [];
}

export interface UnificarCamarasBody {
  camara_principal_id: number | null;
  camara_secundaria_id: number;
  guardar_alias: boolean;
}

export interface FusionarGrupoCamarasBody {
  camara_principal_id: number | null;
  camara_secundaria_ids: number[];
  guardar_alias: boolean;
}

export interface MergeCamarasResponse {
  error?: string;
  ok?: boolean;
}

export async function unificarCamaras(body: UnificarCamarasBody): Promise<MergeCamarasResponse> {
  return requestJson<MergeCamarasResponse>('/api/infra/camaras/merge', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    json: { ...body },
  });
}

export async function fusionarGrupoCamaras(body: FusionarGrupoCamarasBody): Promise<MergeCamarasResponse> {
  return requestJson<MergeCamarasResponse>('/api/infra/camaras/merge-grupo', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    json: { ...body },
  });
}

export interface EstadoContextoItem {
  id: number;
  ticket_asociado: string | null;
  servicio_protegido_id: string;
  ruta_protegida_id: number | null;
}

export interface EstadoContexto {
  estado_actual: string;
  estado_sugerido: string | null;
  tiene_baneo_activo: boolean;
  tiene_ingreso_activo: boolean;
  inconsistente: boolean;
  incidentes_activos: EstadoContextoItem[];
}

export interface EstadoCamaraResponse {
  error?: string;
  contexto?: EstadoContexto;
  estados_disponibles?: string[];
}

export interface CambiarEstadoCamaraResponse {
  error?: string;
  success?: boolean;
}

export async function obtenerEstadoCamara(id: number): Promise<EstadoCamaraResponse> {
  return requestJson<EstadoCamaraResponse>(`/api/infra/camaras/${id}/estado`);
}

export async function cambiarEstadoCamara(id: number, estado: string, motivo: string): Promise<CambiarEstadoCamaraResponse> {
  return requestJson<CambiarEstadoCamaraResponse>(`/api/infra/camaras/${id}/estado`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    json: { estado, motivo },
  });
}

// ── Detalle de Cámara ──

export interface RutaItem {
  ruta_id: number;
  servicio_id: string;
  ruta_nombre: string;
  ruta_tipo: string;
  alias_ids: string[];
  transitos_count: number;
  punta_a_sitio: string | null;
  punta_b_sitio: string | null;
}

export interface CamaraDetail {
  id: number;
  nombre: string;
  direccion: string | null;
  estado: string;
  editable: boolean;
  rutas: RutaItem[];
  es_botella: boolean;
  camara_padre_id: number | null;
  camara_padre_nombre: string | null;
}

export interface AliasItem {
  id: number;
  nombre: string;
  created_at: string | null;
}

export interface BotellaItem {
  id: number;
  nombre: string | null;
  estado: string | null;
  servicios: string[];
  origen: BotellaOrigen;
}

export interface RegistrosContexto {
  estado_actual: string;
  estado_sugerido: string | null;
  tiene_baneo_activo: boolean;
  tiene_ingreso_activo: boolean;
}

export interface RegistrosBaneo {
  id: number;
  ticket_asociado: string | null;
  servicio_protegido_id: string;
  ruta_protegida_id: number | null;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  motivo: string | null;
  activo: boolean;
}

export interface RegistrosAuditoria {
  id: number;
  usuario: string;
  motivo: string;
  estado_anterior: string | null;
  estado_nuevo: string | null;
  estado_sugerido: string | null;
  created_at: string | null;
}

export interface RegistrosIngreso {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
  botella_label: string;
  tipo: string;
  anulado: boolean;
  anulado_at: string | null;
  anulado_por: string | null;
  anulado_motivo: string | null;
}

export interface RegistrosPayload {
  contexto: RegistrosContexto | null;
  baneos: RegistrosBaneo[];
  auditoria: RegistrosAuditoria[];
  ingresos: RegistrosIngreso[];
}

export async function obtenerCamara(id: number): Promise<{ camara: CamaraDetail }> {
  return requestJson<{ camara: CamaraDetail }>(`/api/infra/camaras/${id}`);
}

export async function obtenerAliasesCamara(id: number): Promise<{ aliases?: AliasItem[] }> {
  return requestJson<{ aliases?: AliasItem[] }>(`/api/infra/camaras/${id}/aliases`);
}

/** `qs` es el query string completo (con `?`) o vacío, p. ej. `?incluir_anulados=1`. */
export async function obtenerRegistrosCamara(id: number, qs: string): Promise<RegistrosPayload> {
  return requestJson<RegistrosPayload>(`/api/infra/camaras/${id}/registros${qs}`);
}

export async function obtenerBotellasCamara(id: number): Promise<{ botellas?: BotellaItem[] }> {
  return requestJson<{ botellas?: BotellaItem[] }>(`/api/infra/camaras/${id}/botellas`);
}
