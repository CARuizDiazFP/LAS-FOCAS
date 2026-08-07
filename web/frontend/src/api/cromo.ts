// Nombre de archivo: cromo.ts
// Ubicación de archivo: web/frontend/src/api/cromo.ts
// Descripción: Cliente API y catálogo estático para la ingesta de inventario FO desde Cromo Red (admin)

import { request, requestJson } from './client';

export const CROMO_PSIZE_OPCIONES = [1, 5, 10, 20, 50] as const;
export type CromoPsize = (typeof CROMO_PSIZE_OPCIONES)[number];

export interface CromoCorrida {
  id: number;
  usuario: string;
  estado: string;
  params: Record<string, unknown>;
  total_objetivo: number | null;
  leidas: number;
  creadas: number;
  actualizadas: number;
  sin_cambios: number;
  errores: number;
  refs_colgadas: number;
  iniciada_at: string | null;
  finalizada_at: string | null;
}

export interface CromoEvento {
  id: number;
  n_id: number | null;
  clase: number | null;
  accion: string;
  detalle: string | null;
  created_at: string | null;
}

export interface CromoHistorico {
  total: number;
  limit: number;
  offset: number;
  corridas: CromoCorrida[];
}

export interface CromoDetalle {
  corrida: CromoCorrida;
  eventos: CromoEvento[];
}

/** Catálogo de clases botella/empalme seleccionables al disparar una corrida.
 *
 * Estático a propósito: es el mismo seed de `app.cromo_clases` (migración `20260805_01_cromo_ingesta.py`),
 * cambia con muy poca frecuencia y no justifica un endpoint propio sólo para listarlo. Cables (class 51)
 * y lo que viaja embebido (tubo/pelo/fusión) no son seleccionables acá: cables se barren siempre en la
 * Fase 2, tubo/pelo/fusión llegan con su botella/cable padre.
 */
export interface CromoClaseInfo {
  clase: number;
  etiqueta: string | null;
  seleccionablePorDefecto: boolean;
  homologada: boolean;
  motivoExclusion: string | null;
}

export const CROMO_CATALOGO_BOTELLAS: CromoClaseInfo[] = [
  { clase: 68, etiqueta: '6-1', seleccionablePorDefecto: true, homologada: true, motivoExclusion: null },
  { clase: 121, etiqueta: '16-1', seleccionablePorDefecto: true, homologada: true, motivoExclusion: null },
  { clase: 122, etiqueta: '4-1', seleccionablePorDefecto: true, homologada: true, motivoExclusion: null },
  { clase: 123, etiqueta: '8-1', seleccionablePorDefecto: true, homologada: true, motivoExclusion: null },
  { clase: 125, etiqueta: '5-1', seleccionablePorDefecto: true, homologada: true, motivoExclusion: null },
  { clase: 124, etiqueta: null, seleccionablePorDefecto: false, homologada: false, motivoExclusion: null },
];

export const CROMO_CLASE_EXCLUIDA = {
  clase: 120,
  motivo: 'Parcela catastral, no es planta de FO — nunca se ingiere.',
};

export async function iniciarIngestaCromo(opciones: {
  psize: CromoPsize;
  maxPaginas: number | null;
  clases: number[];
}): Promise<{ corrida_id: number }> {
  return requestJson('/api/admin/ingesta/cromo', {
    method: 'POST',
    json: {
      psize: opciones.psize,
      max_paginas: opciones.maxPaginas,
      clases: opciones.clases,
    },
    csrf: true,
  });
}

export async function cancelarIngestaCromo(corridaId: number): Promise<void> {
  await request(`/api/admin/ingesta/cromo/corridas/${corridaId}/cancelar`, {
    method: 'POST',
    json: {},
    csrf: true,
  });
}

export async function obtenerHistoricoCromo(limit = 10, offset = 0): Promise<CromoHistorico> {
  return requestJson(`/api/admin/ingesta/cromo/corridas?limit=${limit}&offset=${offset}`);
}

export async function obtenerDetalleCromo(corridaId: number): Promise<CromoDetalle> {
  return requestJson(`/api/admin/ingesta/cromo/corridas/${corridaId}`);
}

export function streamUrlIngestaCromo(corridaId: number): string {
  return `/api/admin/ingesta/cromo/corridas/${corridaId}/stream`;
}

// ── Scheduler del worker dedicado (Etapa 7) ──────────────────────────────────
// La ingesta ahora corre en su propio contenedor (modules/cromo_worker/); estas funciones configuran
// y consultan el estado de esa corrida periódica desde el panel admin.

export interface CromoSchedulerConfig {
  habilitado: boolean;
  intervalo_horas: number;
  hora_inicio: number | null;
  psize: CromoPsize;
  max_paginas: number | null;
  clases: number[];
  ultima_ejecucion: string | null;
  ultimo_error: string | null;
}

export interface CromoWorkerHealth {
  status: string;
  habilitado?: boolean;
  intervalo_horas?: number;
  hora_inicio?: number | null;
  ultima_ejecucion?: string | null;
  ultimo_error?: string | null;
  corrida_en_curso?: number | null;
  error?: string;
}

export async function obtenerConfigSchedulerCromo(): Promise<CromoSchedulerConfig> {
  return requestJson('/api/admin/ingesta/cromo/config');
}

export async function guardarConfigSchedulerCromo(config: {
  habilitado: boolean;
  intervaloHoras: number;
  horaInicio: number | null;
  psize: CromoPsize;
  maxPaginas: number | null;
  clases: number[];
}): Promise<void> {
  await request('/api/admin/ingesta/cromo/config', {
    method: 'POST',
    json: {
      habilitado: config.habilitado,
      intervalo_horas: config.intervaloHoras,
      hora_inicio: config.horaInicio,
      psize: config.psize,
      max_paginas: config.maxPaginas,
      clases: config.clases,
    },
    csrf: true,
  });
}

export async function obtenerSaludWorkerCromo(): Promise<CromoWorkerHealth> {
  return requestJson('/api/admin/ingesta/cromo/config/health');
}

export async function dispararSchedulerCromo(): Promise<{ ok: boolean; corrida_id?: number }> {
  return requestJson('/api/admin/ingesta/cromo/config/trigger', {
    method: 'POST',
    json: {},
    csrf: true,
  });
}

// ── Verificador de servicios (Etapa 6) ───────────────────────────────────────
// Consultas de sólo lectura sobre el inventario ya ingerido — sin rol admin, cualquier usuario
// autenticado puede consultarlas (ver docs/Doc Privada/ingesta_cromo.md §8.2).

export interface CromoServicioEncontrado {
  servicio_id: number;
  servicio_id_externo: string;
  numero_primer_servicio: string | null;
  nombre_cliente: string | null;
  cliente: string | null;
  estado_servicio: string | null;
  categoria: number | null;
  tipo_servicio: string | null;
  pelo_n_id: number;
  servicio_numero_match: string;
  metodo: string;
}

export interface CromoVerificacionCable {
  cable_n_id: number;
  nombre: string | null;
  capacidad: string | null;
  extremo_a_nombre: string | null;
  extremo_b_nombre: string | null;
  servicios: CromoServicioEncontrado[];
}

export interface CromoVerificacionTubo {
  tubo_n_id: number;
  cable_n_id: number | null;
  orden: number | null;
  nombre_color: string | null;
  servicios: CromoServicioEncontrado[];
}

export interface CromoVerificacionBotella {
  botella_n_id: number;
  nombre: string | null;
  clase: number | null;
  localidad: string | null;
  servicios: CromoServicioEncontrado[];
}

export async function verificarServiciosPorCable(cableNId: number): Promise<CromoVerificacionCable> {
  return requestJson(`/api/infra/cromo/cables/${cableNId}/servicios`);
}

export async function verificarServiciosPorTubo(tuboNId: number): Promise<CromoVerificacionTubo> {
  return requestJson(`/api/infra/cromo/tubos/${tuboNId}/servicios`);
}

export async function verificarServiciosPorBotella(botellaNId: number): Promise<CromoVerificacionBotella> {
  return requestJson(`/api/infra/cromo/botellas/${botellaNId}/servicios`);
}
