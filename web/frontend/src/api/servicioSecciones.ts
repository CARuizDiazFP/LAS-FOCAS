// Nombre de archivo: servicioSecciones.ts
// Ubicación de archivo: web/frontend/src/api/servicioSecciones.ts
// Descripción: Cliente y tipos de las secciones del Detalle de Servicio (camino FO, ODFs, ingresos,
// reclamos y baneos) — compartidos entre la ficha compacta y cada vista dedicada

/**
 * Estos tipos y llamadas vivían declarados INLINE dentro de `ServicioDetalleView.vue`, junto con
 * cinco `fetch` crudos y un `parseJsonOrError` duplicado. Al partir la ficha en tarjetas con una
 * vista propia por sección, cada una necesita los mismos datos: dejarlos en la vista habría
 * obligado a duplicarlos cinco veces.
 *
 * Todas las llamadas pasan por `requestJson`, que ya unifica el manejo de errores del SPA.
 */

import { requestJson } from './client';

// ── Camino FO (tracking legado por ruta) ──────────────────────────────────

export interface InfraRutaItem {
  id: number;
  nombre: string;
  tipo: string;
  empalmes_count: number;
  activa: boolean;
}

export interface InfraRutasResponse {
  status: string;
  rutas: InfraRutaItem[];
}

export interface TrackingEntry {
  tipo: string;
}

export interface InfraPunta {
  sitio?: string | null;
  identificador?: string | null;
  conector?: string | null;
}

export interface InfraTrackingResponse {
  status: string;
  tracking: TrackingEntry[];
  punta_a?: InfraPunta | null;
  punta_b?: InfraPunta | null;
}

export async function getRutasServicio(idOrigen: string): Promise<InfraRutasResponse> {
  return requestJson<InfraRutasResponse>(
    `/api/infra/servicios/${encodeURIComponent(idOrigen)}/rutas`,
  );
}

export async function getTrackingRuta(rutaId: number): Promise<InfraTrackingResponse> {
  return requestJson<InfraTrackingResponse>(`/api/infra/rutas/${rutaId}/tracking`);
}

// ── ODFs asociadas ────────────────────────────────────────────────────────

/**
 * Fuente: el archivo de tracking de la ruta, no Cromo. `empalme_id` siempre viene como string
 * (regex del parser); `camara_*` son `null` cuando no hay match en `app.empalmes`; `ruta_tipo`
 * nunca llega `null` desde el backend (default "PRINCIPAL" ya resuelto server-side).
 */
export interface InfraOdfTerminal {
  odf_id: string;
  conector: string;
}

export interface InfraOdfEmpalme {
  empalme_id: string;
  descripcion: string;
  es_transito: boolean;
  camara_id: number | null;
  camara_nombre: string | null;
  camara_estado: string | null;
}

export interface InfraOdfRuta {
  ruta_id: number;
  ruta_nombre: string;
  ruta_tipo: string;
  activa: boolean;
  sin_tracking: boolean;
  terminal_a: InfraOdfTerminal | null;
  terminal_b: InfraOdfTerminal | null;
  transitos_count: number;
  empalmes_count: number;
  empalmes: InfraOdfEmpalme[];
}

export interface InfraOdfsResponse {
  status: string;
  servicio_id: string;
  total_odfs: number;
  total_empalmes: number;
  rutas: InfraOdfRuta[];
}

export async function getOdfsServicio(idOrigen: string): Promise<InfraOdfsResponse> {
  return requestJson<InfraOdfsResponse>(
    `/api/infra/servicios/${encodeURIComponent(idOrigen)}/odfs`,
  );
}

// ── Ingresos técnicos ─────────────────────────────────────────────────────

/**
 * Ingresos técnicos (Slack) a las cámaras que atraviesa el servicio. `tecnico_id` guarda el nombre
 * resuelto del técnico (vía Slack `users.info`) para filas creadas desde el fix de 2026-09-04 en
 * adelante — filas anteriores a ese deploy pueden todavía tener el id crudo de Slack (p. ej.
 * "U0AUB6CRE4A") si nunca se cerraron con un Egreso posterior. `botella_label`/`tipo` distinguen la
 * Botella resuelta y un `INTENTO_BLOQUEADO` (que también tiene `fecha_fin: null`, igual que un
 * ingreso real "en curso") de un ingreso real.
 */
export interface InfraServicioIngreso {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
  botella_label: string;
  tipo: string;
  camara_id: number;
  camara_nombre: string | null;
}

export interface InfraServicioIngresosResponse {
  status: string;
  servicio_id: string;
  total: number;
  ingresos: InfraServicioIngreso[];
}

export async function getIngresosServicio(
  idOrigen: string,
): Promise<InfraServicioIngresosResponse> {
  return requestJson<InfraServicioIngresosResponse>(
    `/api/infra/servicios/${encodeURIComponent(idOrigen)}/ingresos`,
  );
}

// ── Reportes ──────────────────────────────────────────────────────────────

export interface ReportHistoryItem {
  id: number;
  status: string;
  started_at: string | null;
  report_type: string;
}

export interface ReportsHistoryResponse {
  items?: ReportHistoryItem[];
}

export async function getUltimoReporte(tipo: 'sla' | 'repetitividad'): Promise<ReportsHistoryResponse> {
  return requestJson<ReportsHistoryResponse>(`/api/reports/history?type=${tipo}&limit=1`);
}

// ── Baneos ────────────────────────────────────────────────────────────────

/**
 * `rol` distingue si el Servicio fue el **protegido** (se baneó a otros para cuidarlo) o el
 * **afectado** (se lo baneó para cuidar a un tercero): son dos lecturas muy distintas de la misma
 * fila. El backend matchea por las tres identidades del Servicio, porque `app.incidentes_baneo`
 * guarda los extremos como texto y no como FK.
 */
export interface ServicioBaneo {
  id: number;
  ticket_asociado: string | null;
  servicio_afectado_id: string;
  servicio_protegido_id: string;
  usuario_ejecutor: string | null;
  motivo: string | null;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  activo: boolean;
  rol: 'PROTEGIDO' | 'AFECTADO' | string;
}

export interface ServicioBaneosResponse {
  servicio_id: number;
  total: number;
  activos: number;
  eventos: ServicioBaneo[];
}

export async function getBaneosServicio(servicioId: number): Promise<ServicioBaneosResponse> {
  return requestJson<ServicioBaneosResponse>(`/api/servicios/${servicioId}/baneos`);
}
