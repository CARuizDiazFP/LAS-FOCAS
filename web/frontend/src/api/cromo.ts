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

// ── Inventario de cables (Etapa 8b) ──────────────────────────────────────────
// Distinto del verificador: "listame/buscame cables" (con paginación), no "qué servicios pasan por
// este cable puntual". Mismo criterio de auth que el verificador — cualquier usuario autenticado.

export interface CromoCableInventario {
  n_id: number;
  nombre: string | null;
  capacidad: string | null;
  capacidad_pelos: number | null;
  jerarquia: string | null;
  propietario: string | null;
  extremo_a_nombre: string | null;
  extremo_b_nombre: string | null;
  vigente: boolean;
  cantidad_servicios: number;
}

export interface CromoInventarioCablesResultado {
  total: number;
  limit: number;
  offset: number;
  cables: CromoCableInventario[];
}

export async function buscarInventarioCables(opciones: {
  q?: string;
  jerarquia?: string;
  propietario?: string;
  vigente?: boolean;
  nId?: number;
  botella?: string;
  servicio?: string;
  limit?: number;
  offset?: number;
}): Promise<CromoInventarioCablesResultado> {
  const params = new URLSearchParams();
  if (opciones.q) params.set('q', opciones.q);
  if (opciones.jerarquia) params.set('jerarquia', opciones.jerarquia);
  if (opciones.propietario) params.set('propietario', opciones.propietario);
  if (opciones.vigente !== undefined) params.set('vigente', String(opciones.vigente));
  if (opciones.nId !== undefined) params.set('n_id', String(opciones.nId));
  if (opciones.botella) params.set('botella', opciones.botella);
  if (opciones.servicio) params.set('servicio', opciones.servicio);
  params.set('limit', String(opciones.limit ?? 50));
  params.set('offset', String(opciones.offset ?? 0));
  return requestJson(`/api/infra/cromo/cables?${params.toString()}`);
}

// ── Detalle jerárquico de un cable (Etapa 9) ─────────────────────────────────
// Distinto del verificador (servicios que pasan por el cable) y del inventario (listar/buscar):
// esto es "mostrame la jerarquía completa de este cable puntual" — extremos, tubos/buffers y sus
// pelos, con el servicio matcheado de cada pelo si existe.

export interface CromoExtremoCable {
  n_id: number | null;
  clase: number | null;
  legacy: string | null;
  nombre: string | null;
}

export interface CromoPeloDetalle {
  n_id: number;
  numero_pelo: string | null;
  orden: number | null;
  color: string | null;
  tipo_asociacion: string;
  servicio_raw: string | null;
  servicio_numero: string | null;
  vigente: boolean;
  servicios: CromoServicioEncontrado[];
}

export interface CromoTuboDetalle {
  n_id: number;
  orden: number | null;
  nombre_color: string | null;
  vigente: boolean | null;
  tiene_fila_propia: boolean;
  pelos: CromoPeloDetalle[];
}

export interface CromoDetalleCable {
  n_id: number;
  nombre: string | null;
  capacidad: string | null;
  capacidad_pelos: number | null;
  jerarquia: string | null;
  propietario: string | null;
  tendido: string | null;
  distancia_geo: number | null;
  distancia_real: number | null;
  id_legacy: string | null;
  notas: string | null;
  vigente: boolean;
  extremo_a: CromoExtremoCable;
  extremo_b: CromoExtremoCable;
  tubos: CromoTuboDetalle[];
}

export async function obtenerDetalleCable(nId: number): Promise<CromoDetalleCable> {
  return requestJson(`/api/infra/cromo/cables/${nId}/detalle`);
}
