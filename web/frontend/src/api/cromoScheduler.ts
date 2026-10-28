// Nombre de archivo: cromoScheduler.ts
// Ubicación de archivo: web/frontend/src/api/cromoScheduler.ts
// Descripción: Cliente API del scheduler del worker dedicado de la ingesta Cromo Red (admin)

import { request, requestJson } from './client';
import type { CromoPsize } from './cromoIngesta';

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
