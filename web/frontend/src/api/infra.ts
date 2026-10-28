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
 * multipart: `include_xls` / `include_txt` indican si se adjunta el resumen XLS / el tracking TXT.
 */
export async function descargarEmlBaneo(body: {
  incident_id: number;
  recipients: string;
  subject: string;
  html_body: string;
  include_xls: boolean;
  include_txt: boolean;
}): Promise<string> {
  return requestDownload('/api/infra/notify/download-eml', {
    method: 'POST',
    json: body,
    fallbackFilename: `aviso_baneo_${body.incident_id}.eml`,
  });
}

// --- Búsqueda de cámaras ---

export interface SmartSearchBody {
  terms: string[];
  limit: number;
  offset: number;
  incluir_no_operativas: boolean;
  estado?: string;
}

export interface SmartSearchResponse {
  camaras?: Record<string, unknown>[];
  total?: number;
}

export async function smartSearch(body: SmartSearchBody): Promise<SmartSearchResponse> {
  return requestJson<SmartSearchResponse>('/api/infra/smart-search', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    json: { ...body },
  });
}

export async function exportarCamaras(params: URLSearchParams): Promise<string> {
  return requestDownload(`/api/infra/export/cameras?${params.toString()}`, {
    fallbackFilename: `camaras_${Date.now()}.${params.get('format') === 'csv' ? 'csv' : 'xlsx'}`,
  });
}

// --- Rutas y tracking ---

export interface BanRutaOption {
  id: number;
  nombre: string;
  tipo: string;
  empalmes_count: number;
  activa: boolean;
  hash_contenido: string | null;
}

export async function rutasDeServicio(servicioId: string): Promise<{ rutas?: BanRutaOption[] }> {
  return requestJson<{ rutas?: BanRutaOption[] }>(`/api/infra/servicios/${encodeURIComponent(servicioId)}/rutas`);
}

/** Descarga el `.txt` original de la ruta. Si no existe el backend responde 404 (`ApiError.status`). */
export async function descargarTrackingRuta(rutaId: number): Promise<string> {
  return requestDownload(`/api/infra/tracking/${rutaId}/download`, {
    fallbackFilename: `tracking_ruta_${rutaId}.txt`,
  });
}

// --- Baneos (protocolo de protección) ---

export interface IncidenteActivo {
  id: number;
  ticket_asociado: string | null;
  servicio_afectado_id: string;
  servicio_protegido_id: string;
  ruta_protegida_id: number | null;
  usuario_ejecutor: string | null;
  motivo: string | null;
  fecha_inicio: string | null;
  activo: boolean;
  duracion_horas: number | null;
  camaras_count: number;
}

export async function baneosActivos(): Promise<{ incidentes?: IncidenteActivo[] }> {
  return requestJson<{ incidentes?: IncidenteActivo[] }>('/api/infra/ban/active');
}

export async function levantarBaneo(body: { incidente_id: number }): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/infra/ban/lift', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    json: body,
  });
}

export interface CrearBaneoBody {
  ticket_asociado: string | null;
  servicio_afectado_id: string;
  servicio_protegido_id: string;
  ruta_protegida_id: number | null;
  motivo: string | null;
  usuario_ejecutor: string | null;
}

export async function crearBaneo(body: CrearBaneoBody): Promise<{ camaras_baneadas?: number }> {
  return requestJson<{ camaras_baneadas?: number }>('/api/infra/ban/create', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    json: { ...body },
  });
}

export interface NotificarBaneoEmailBody {
  to: string[];
  cc?: string[];
  subject: string;
  body: string;
  incidente_ids: number[];
  include_xls: boolean;
  include_txt: boolean;
}

export interface NotificarBaneoEmailResponse {
  success?: boolean;
  error?: string;
  detail?: string;
}

export async function notificarBaneoEmail(body: NotificarBaneoEmailBody): Promise<NotificarBaneoEmailResponse> {
  return requestJson<NotificarBaneoEmailResponse>('/api/infra/notify/email', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    json: { ...body },
  });
}

// --- Carga de trackings (flujo Portero 2 fases) ---

export interface RutaInfo {
  id: number; nombre: string; tipo: string; empalmes_count: number; activa: boolean;
}
export interface UpgradeInfo {
  old_service_id: string; old_service_db_id: number; new_service_id: string;
  match_reason: string; punta_a_match?: string | null; punta_b_match?: string | null;
}
export interface StrandInfo {
  service_id: string; service_db_id: number; ruta_id: number;
  current_strands: number; new_strand_pelo?: string | null;
}
export interface AnalyzeResult {
  status: string; servicio_id?: string | null; servicio_db_id?: number | null;
  rutas_existentes: RutaInfo[]; parsed_empalmes_count: number; message: string;
  error?: string | null; upgrade_info?: UpgradeInfo | null; strand_info?: StrandInfo | null;
  punta_a_sitio?: string | null; punta_b_sitio?: string | null;
}

/** Respuesta de POST /api/infra/trackings/resolve. `ubicaciones_sin_match` queda en IngresoSinMatch. */
export interface ResolveResponse {
  success: boolean; message?: string; error?: string; detail?: string;
  ubicaciones_sin_match?: number;
}

export interface ResolverTrackingBody {
  action: string;
  content: string;
  filename: string;
  target_ruta_id?: number | null;
  new_ruta_name?: string;
  new_ruta_tipo?: string;
  old_service_id?: string;
}

export async function analizarTracking(data: FormData): Promise<AnalyzeResult> {
  return requestJson<AnalyzeResult>('/api/infra/trackings/analyze', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    formData: data,
  });
}

export async function resolverTracking(body: ResolverTrackingBody): Promise<ResolveResponse> {
  return requestJson<ResolveResponse>('/api/infra/trackings/resolve', {
    method: 'POST',
    headers: { Accept: 'application/json' },
    json: { ...body },
  });
}

export async function limpiarEmpalmesServicio(servicioId: string): Promise<{ message?: string }> {
  return requestJson<{ message?: string }>(`/api/infra/servicios/${encodeURIComponent(servicioId)}/empalmes`, {
    method: 'DELETE',
    headers: { Accept: 'application/json' },
  });
}
