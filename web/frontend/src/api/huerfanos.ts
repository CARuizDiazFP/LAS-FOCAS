// Nombre de archivo: huerfanos.ts
// Ubicación de archivo: web/frontend/src/api/huerfanos.ts
// Descripción: Cliente frontend de la auditoría de huérfanos — listado paginado con filtros,
// normalizar/descartar en lote y auditoría global (corrida del cromo_worker)

import { requestJson } from './client';

// Mismos literales que `core/services/cromo/auditoria_huerfanos.py` (CAUSAS / ESTADOS) y los CHECK
// de `app.cromo_auditoria_huerfanos`.
export const CAUSAS_HUERFANO = [
  'CABLE_DESUSO',
  'PELO_DANADO',
  'CAMBIO_CABLE_DANO',
  'MIGRACION_SITIO',
  'SIN_CLASIFICAR',
] as const;

export type CausaHuerfano = (typeof CAUSAS_HUERFANO)[number];

export const ESTADOS_HUERFANO = ['PENDIENTE', 'NORMALIZADO', 'DESCARTADO'] as const;

const CAUSA_LABELS: Record<CausaHuerfano, string> = {
  CABLE_DESUSO: 'Cable en desuso',
  PELO_DANADO: 'Pelo dañado',
  CAMBIO_CABLE_DANO: 'Cambio de cable por daño',
  MIGRACION_SITIO: 'Migración de sitio',
  SIN_CLASIFICAR: 'Sin clasificar',
};

export function causaHuerfanoLabel(causa: string): string {
  return CAUSA_LABELS[causa as CausaHuerfano] ?? causa;
}

export interface EvidenciaHuerfano {
  protegido?: boolean;
  motivo_proteccion?: string | null;
  senales?: {
    cables?: number;
    cables_sin_uso?: number;
    cables_compartidos_con_tramos?: number;
    paralelo_a_tramo?: boolean;
    botellas_extremas?: number[];
    botellas_fuera_de_tramos?: number[];
    odfs_extremas?: number[];
    tramos?: number;
  };
  camino?: { semilla?: number; pelos?: number; cables?: number[] };
}

export interface HuerfanoItem {
  id: number;
  servicio_id: number;
  servicio_numero: string;
  pelo_n_id: number;
  numero_pelo: string | null;
  color: string | null;
  cable_n_id: number | null;
  cable_nombre: string | null;
  camino_semilla: number | null;
  causa: string;
  evidencia: EvidenciaHuerfano;
  protegido: boolean;
  estado: string;
  normalizable: boolean;
  revisado_por: string | null;
  corrida_id: number | null;
  detectado_at: string | null;
  actualizado_at: string | null;
}

export interface ListadoHuerfanosResponse {
  total: number;
  limit: number;
  offset: number;
  items: HuerfanoItem[];
  /** Con los filtros de servicio y estado, antes del de causa (para los chips). */
  conteos_por_causa: Record<string, number>;
}

export interface ListarHuerfanosParams {
  servicio_id?: number;
  causa?: string;
  estado?: string;
  limit?: number;
  offset?: number;
}

function toQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function listarHuerfanos(params: ListarHuerfanosParams): Promise<ListadoHuerfanosResponse> {
  return requestJson<ListadoHuerfanosResponse>(
    `/api/admin/infra/huerfanos${toQuery({
      servicio_id: params.servicio_id,
      causa: params.causa,
      estado: params.estado,
      limit: params.limit,
      offset: params.offset,
    })}`,
  );
}

export interface ResultadoRevisionHuerfanos {
  ok: boolean;
  aplicados: number[];
  rechazados: { id: number; motivo: string }[];
}

export async function normalizarHuerfanos(ids: number[]): Promise<ResultadoRevisionHuerfanos> {
  return requestJson<ResultadoRevisionHuerfanos>('/api/admin/infra/huerfanos/normalizar', {
    method: 'POST',
    json: { ids },
    csrf: true,
  });
}

export async function descartarHuerfanos(ids: number[]): Promise<ResultadoRevisionHuerfanos> {
  return requestJson<ResultadoRevisionHuerfanos>('/api/admin/infra/huerfanos/descartar', {
    method: 'POST',
    json: { ids },
    csrf: true,
  });
}

// ── Auditoría global (corrida sintética del cromo_worker) ─────────────────

export interface CorridaAuditoria {
  id: number;
  estado: string;
  total_objetivo: number | null;
  leidas: number;
  actualizadas: number;
  errores: number;
  iniciada_at: string | null;
  finalizada_at: string | null;
}

export interface EstadoAuditoriaGlobal {
  corrida: CorridaAuditoria | null;
  max_servicios_default: number;
}

export async function obtenerAuditoriaGlobal(): Promise<EstadoAuditoriaGlobal> {
  return requestJson<EstadoAuditoriaGlobal>('/api/admin/infra/huerfanos/auditoria-global');
}

export async function lanzarAuditoriaGlobal(
  maxServicios?: number,
): Promise<{ corrida_id: number; max_servicios: number }> {
  return requestJson('/api/admin/infra/huerfanos/auditoria-global', {
    method: 'POST',
    json: maxServicios ? { max_servicios: maxServicios } : {},
    csrf: true,
  });
}
