// Nombre de archivo: cromoInventario.ts
// Ubicación de archivo: web/frontend/src/api/cromoInventario.ts
// Descripción: Cliente API del inventario de cables, ODFs y red de acceso PON de Cromo

import { requestJson } from './client';

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

// ── Inventario de ODFs (Tarea 5, plan ODFs) ──────────────────────────────────
// Mismo criterio que el inventario de cables: "listame/buscame ODFs" (con paginación), no "qué
// servicios pasan por este ODF puntual" (eso es `verificarServiciosPorOdf` más abajo).

export interface CromoOdfInventario {
  n_id: number;
  nombre: string | null;
  tipo_elemento: string;
  localidad: string | null;
  calle: string | null;
  altura: string | null;
  propietario: string | null;
  vigente: boolean;
  cantidad_cables_asociados: number;
  cantidad_servicios: number;
}

export interface CromoInventarioOdfsResultado {
  total: number;
  limit: number;
  offset: number;
  odfs: CromoOdfInventario[];
}

export async function buscarInventarioOdfs(opciones: {
  q?: string;
  nId?: number;
  vigente?: boolean;
  tipoElemento?: string;
  servicio?: string;
  limit?: number;
  offset?: number;
}): Promise<CromoInventarioOdfsResultado> {
  const params = new URLSearchParams();
  if (opciones.q) params.set('q', opciones.q);
  if (opciones.nId !== undefined) params.set('n_id', String(opciones.nId));
  if (opciones.vigente !== undefined) params.set('vigente', String(opciones.vigente));
  if (opciones.tipoElemento) params.set('tipo_elemento', opciones.tipoElemento);
  if (opciones.servicio) params.set('servicio', opciones.servicio);
  params.set('limit', String(opciones.limit ?? 50));
  params.set('offset', String(opciones.offset ?? 0));
  return requestJson(`/api/infra/cromo/odfs?${params.toString()}`);
}

// ── Inventario de la red de acceso PON (2026-09-19) ──────────────────────────
// Cajas PON y rosetas viven en la misma tabla porque comparten esquema; lo que separa una vista de
// la otra es la lista de clases que pide. Por eso `clases` es un parámetro y no hay dos funciones.

/** Las siete clases de caja PON, medidas contra Cromo. Hasta 2026-09-19 el sistema sólo conocía la
 * 84 y la 137; las otras cinco (126, 127, 138, 139, 140) no estaban en ninguna lista y el diagrama
 * de camino óptico las dibujaba como "CLASE_139". */
export const CROMO_CLASES_CAJA_PON = [84, 126, 127, 137, 138, 139, 140] as const;
export const CROMO_CLASE_ROSETA = 85;

export interface CromoPonElementoInventario {
  n_id: number;
  clase: number;
  nombre: string | null;
  localidad: string | null;
  calle: string | null;
  altura: string | null;
  propietario: string | null;
  tipo_conector: string | null;
  capacidad_puertos: number | null;
  latitud: number | null;
  longitud: number | null;
  vigente: boolean;
  cantidad_splitters: number;
}

export interface CromoInventarioPonResultado {
  total: number;
  limit: number;
  offset: number;
  elementos: CromoPonElementoInventario[];
}

export async function buscarInventarioPon(opciones: {
  q?: string;
  nId?: number;
  clases?: readonly number[];
  vigente?: boolean;
  localidad?: string;
  propietario?: string;
  limit?: number;
  offset?: number;
}): Promise<CromoInventarioPonResultado> {
  const params = new URLSearchParams();
  if (opciones.q) params.set('q', opciones.q);
  if (opciones.nId !== undefined) params.set('n_id', String(opciones.nId));
  if (opciones.clases && opciones.clases.length > 0) params.set('clases', opciones.clases.join(','));
  if (opciones.vigente !== undefined) params.set('vigente', String(opciones.vigente));
  if (opciones.localidad) params.set('localidad', opciones.localidad);
  if (opciones.propietario) params.set('propietario', opciones.propietario);
  params.set('limit', String(opciones.limit ?? 50));
  params.set('offset', String(opciones.offset ?? 0));
  return requestJson(`/api/infra/cromo/pon?${params.toString()}`);
}
