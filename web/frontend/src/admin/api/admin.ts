// Nombre de archivo: admin.ts
// Ubicación de archivo: web/frontend/src/admin/api/admin.ts
// Descripción: Wrappers fetch para todos los endpoints del panel admin

import { createFormData, request, requestJson } from '../../api/client';

// ─── Tipos ───────────────────────────────────────────────────────────────

export interface AdminUser {
  username: string;
  role: string;
}

export interface BaneosConfig {
  intervalo_horas: number;
  slack_channels: string;
  activo: boolean;
  hora_inicio: number | null;
  ultima_ejecucion: string | null;
  ultimo_error: string | null;
}

export interface WorkerHealth {
  status: string;
  intervalo_horas?: number;
  last_run?: string;
  last_error?: string | null;
  listener_activo?: boolean;
}

export interface ListenerConfig {
  activo: boolean;
  canal_id: string;
  ultimo_error: string | null;
  workflow_ids: string;
  solo_workflows: boolean;
}

// ─── Endpoints ───────────────────────────────────────────────────────────

/** Devuelve el usuario admin autenticado, lanza Error si no es admin. */
export async function getAdminMe(): Promise<AdminUser> {
  return requestJson<AdminUser>('/api/admin/me');
}

/** Crea un nuevo usuario. */
export async function createUser(
  username: string,
  password: string,
  role: string,
): Promise<void> {
  await request('/api/admin/users', {
    method: 'POST',
    formData: createFormData({ username, password, role }),
  });
}

/** Cambia la contraseña del usuario autenticado. */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await request('/api/users/change-password', {
    method: 'POST',
    formData: createFormData({ current_password: currentPassword, new_password: newPassword }),
  });
}

/** Obtiene la configuración del worker de baneos. */
export async function getBaneosConfig(): Promise<BaneosConfig> {
  return requestJson<BaneosConfig>('/api/admin/servicios/baneos/config');
}

/** Guarda la configuración del worker de baneos. */
export async function saveBaneosConfig(
  intervaloHoras: number,
  slackChannels: string,
  activo: boolean,
  horaInicio: number | null,
): Promise<void> {
  const payload: Record<string, string | number | boolean> = {
    intervalo_horas: intervaloHoras,
    slack_channels: slackChannels,
    activo: activo ? 'on' : 'off',
    hora_inicio: horaInicio !== null ? horaInicio : '',
  };
  const res = await request('/api/admin/servicios/baneos', {
    method: 'POST',
    formData: createFormData(payload),
    throwOnError: false,
  });
  if (res.status === 303 || res.ok) return; // redirect = éxito
  const data = await res.json().catch(() => ({}));
  throw new Error((data as { error?: string }).error ?? `Error ${res.status}`);
}

/** Inicia el contenedor del worker si está detenido. */
export async function startWorker(): Promise<{ status: string; msg?: string; container_status?: string }> {
  return requestJson<{ status: string; msg?: string; container_status?: string }>('/api/admin/servicios/baneos/worker/start', {
    method: 'POST',
    formData: createFormData({}),
  });
}

/** Dispara una ejecución manual inmediata del worker. */
export async function triggerManualNotification(): Promise<{ ok: boolean; msg?: string }> {
  return requestJson<{ ok: boolean; msg?: string }>('/api/admin/servicios/baneos/trigger', {
    method: 'POST',
    formData: createFormData({}),
  });
}

/** Verifica el estado del worker de baneos. */
export async function getBaneosHealth(): Promise<WorkerHealth> {
  return requestJson<WorkerHealth>('/api/admin/servicios/baneos/health');
}

/** Devuelve la configuración del listener de ingresos. */
export async function getListenerConfig(): Promise<ListenerConfig> {
  return requestJson<ListenerConfig>('/api/admin/servicios/baneos/listener');
}

/** Guarda la configuración del listener de ingresos. */
export async function saveListenerConfig(
  activo: boolean,
  canalId: string,
  workflowIds: string,
  soloWorkflows: boolean,
): Promise<void> {
  await request('/api/admin/servicios/baneos/listener', {
    method: 'POST',
    formData: createFormData({
      activo: activo ? 'on' : 'off',
      canal_id: canalId,
      workflow_ids: workflowIds,
      solo_workflows: soloWorkflows ? 'on' : 'off',
    }),
  });
}

// ── Cámaras pendientes de revisión ──────────────────────────────────────

export interface CamaraPendiente {
  id: number;
  nombre: string;
  last_update: string | null;
  estado: string;
}

export async function getCamarasPendientes(): Promise<CamaraPendiente[]> {
  return requestJson<CamaraPendiente[]>('/api/admin/infra/camaras/pendientes');
}

export async function aprobarCamara(id: number): Promise<void> {
  await request(`/api/admin/infra/camaras/${id}/aprobar`, {
    method: 'POST',
  });
}

export async function convertirAlias(id: number, camaraDestinoId: number): Promise<void> {
  await request(`/api/admin/infra/camaras/${id}/convertir-alias`, {
    method: 'POST',
    json: { camara_destino_id: camaraDestinoId },
    csrf: true,
  });
}

export async function darDeAltaComoCanon(id: number, nombreCanon: string): Promise<void> {
  await request(`/api/admin/infra/camaras/${id}/dar-de-alta`, {
    method: 'POST',
    json: { nombre_canon: nombreCanon },
    csrf: true,
  });
}

export async function eliminarCamaraPendiente(id: number): Promise<void> {
  await request(`/api/admin/infra/camaras/pendientes/${id}`, {
    method: 'DELETE',
  });
}

// ── Ingresos sin match (reemplaza el auto-registro PENDIENTE_REVISION, 2026-08-11) ─────────

export interface IngresoSinMatch {
  id: number;
  texto_original: string;
  origen: 'slack' | 'tracking' | 'excel_camaras';
  contexto: string | null;
  revisado: boolean;
  created_at: string | null;
}

export async function getIngresosSinMatch(revisado?: boolean, origen?: string): Promise<IngresoSinMatch[]> {
  const params = new URLSearchParams();
  if (revisado !== undefined) params.set('revisado', String(revisado));
  if (origen) params.set('origen', origen);
  const qs = params.toString();
  return requestJson<IngresoSinMatch[]>(`/api/admin/infra/ingresos-sin-match${qs ? `?${qs}` : ''}`);
}

export async function marcarRevisadoIngresoSinMatch(id: number): Promise<void> {
  await request(`/api/admin/infra/ingresos-sin-match/${id}/marcar-revisado`, {
    method: 'POST',
  });
}

export async function marcarRevisadoMasivo(ids: number[]): Promise<{ ok: boolean; actualizados: number }> {
  return requestJson('/api/admin/infra/ingresos-sin-match/marcar-revisado-masivo', {
    method: 'POST',
    json: { ids },
    csrf: true,
  });
}

// ── Grupos baneados (Cámara padre + Botellas) — listado admin y liberación masiva ──────────
// Tipos y endpoints verificados contra `core/services/baneos_grupos_service.py` y los 2 endpoints
// reales en `web/app/main.py` (`GET /api/admin/baneos/grupos`, `POST /api/admin/baneos/grupos/liberar`).

export interface BotellaBaneadaResumen {
  origen: 'legado' | 'cromo';
  id: number;
  nombre: string;
  estado: string;
}

export interface GrupoBaneado {
  camara_id: number;
  nombre: string;
  direccion: string | null;
  fontine_id: string | null;
  estado: string;
  botellas: BotellaBaneadaResumen[];
  botellas_count: number;
  motivo: string | null;
  usuario: string | null;
  fecha: string | null;
  tiene_baneo_activo: boolean;
  // Signal ESTRECHO (sólo IncidenteBaneo activo, no cualquier baneo manual) — es el que gobierna
  // `puede_liberar` y el guard de "forzar" en el backend (`baneos_grupos_service.py`, fix
  // 2026-09-04). Usar este campo (no `tiene_baneo_activo`) para el badge/mensaje de "necesita
  // forzar" — un grupo baneado sólo manualmente (sin incidente) siempre puede liberarse sin forzar.
  tiene_incidente_activo: boolean;
  ticket_baneo: string | null;
  incidentes_activos_ids: number[];
  estado_mixto: boolean;
  puede_liberar: boolean;
}

export interface GruposBaneadosResponse {
  total: number;
  grupos: GrupoBaneado[];
}

export async function getGruposBaneados(params: { q?: string; limit?: number; offset?: number }): Promise<GruposBaneadosResponse> {
  const query = new URLSearchParams();
  if (params.q) query.set('q', params.q);
  if (params.limit !== undefined) query.set('limit', String(params.limit));
  if (params.offset !== undefined) query.set('offset', String(params.offset));
  const qs = query.toString();
  return requestJson<GruposBaneadosResponse>(`/api/admin/baneos/grupos${qs ? `?${qs}` : ''}`);
}

export interface ResultadoLiberarGrupo {
  camara_id: number;
  liberado: boolean;
  estado_final: string | null;
  razon_omision: string | null;
}

export interface LiberarGruposMasivoResponse {
  total_solicitados: number;
  liberados: number;
  omitidos: number;
  detalle: ResultadoLiberarGrupo[];
}

export async function liberarGruposMasivo(camaraIds: number[], motivo: string, forzar = false): Promise<LiberarGruposMasivoResponse> {
  return requestJson<LiberarGruposMasivoResponse>('/api/admin/baneos/grupos/liberar', {
    method: 'POST',
    json: { camara_ids: camaraIds, motivo, forzar },
    csrf: true,
  });
}
