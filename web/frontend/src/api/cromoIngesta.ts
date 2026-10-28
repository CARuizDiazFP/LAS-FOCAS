// Nombre de archivo: cromoIngesta.ts
// Ubicación de archivo: web/frontend/src/api/cromoIngesta.ts
// Descripción: Cliente API de la ingesta Cromo Red: corridas, modos, catálogo estático, histórico y detalle (admin)

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

/** Alcance de una corrida de ingesta.
 *
 * Antes eran dos modos y la vista los tenía hardcodeados como `<option>`, con tres comparaciones
 * literales a `'SOLO_ODF'` dispersas por el template y el script. Con siete, cada modo nuevo sería
 * otra comparación más que olvidarse de agregar: por eso el catálogo es dato y la vista lo itera.
 * Agregar un modo pasa a ser una fila acá.
 *
 * `usaClasesBotella` es la única condición que la vista necesita: dice si la grilla de clases de
 * botella aplica a este modo o si hay que ignorarla y mandarla vacía.
 *
 * El backend valida contra `core.services.cromo.ingesta.MODOS_INGESTA`, que se deriva de la tabla
 * que declara qué fase corre cada modo. Esta lista tiene que decir lo mismo.
 *
 * Duraciones medidas contra Cromo real el 2026-09-19, para que el operador sepa en qué se mete
 * antes de apretar el botón: ninguna de las de la red de acceso entra en "Completa".
 */
export interface CromoModoInfo {
  valor: string;
  etiqueta: string;
  hint: string;
  usaClasesBotella: boolean;
}

export const CROMO_MODOS_INGESTA_INFO: readonly CromoModoInfo[] = [
  {
    valor: 'COMPLETA',
    etiqueta: 'Completa (cables + botellas + fusiones + ODFs)',
    hint: 'La secuencia de siempre. No incluye ninguna clase de la red de acceso PON: sumarlas convertiría una corrida de rutina en una de varias horas.',
    usaClasesBotella: true,
  },
  {
    valor: 'SOLO_ODF',
    etiqueta: 'ODFs y ODF Nodo (clases 69 y 86)',
    hint: 'Corre únicamente la fase de ODFs y ODF Nodo, sin tocar cables, botellas ni fusiones. ~35 min.',
    usaClasesBotella: false,
  },
  {
    valor: 'SOLO_SPLITTERS',
    etiqueta: 'Sólo splitters (clase 133)',
    hint: '20.238 splitters de toda la red, no sólo los que cuelgan de una botella: el 88 % cuelga de una caja PON y por la vía del árbol de botella eran invisibles. ~22 min.',
    usaClasesBotella: false,
  },
  {
    valor: 'SOLO_PUERTOS_SPLITTER',
    etiqueta: 'Sólo puertos de splitter (clase 134)',
    hint: '154.284 puertos, ~91 min. Aporta nombre, sentido y de qué splitter cuelga cada puerto; la ocupación por servicio NO se releva por esta vía.',
    usaClasesBotella: false,
  },
  {
    valor: 'SOLO_CAJAS_PON',
    etiqueta: 'Sólo cajas PON (7 clases)',
    hint: '13.482 cajas PON de las clases 84, 126, 127, 137, 138, 139 y 140 — las cinco últimas no existían en el catálogo hasta ahora. ~2 h.',
    usaClasesBotella: false,
  },
  {
    valor: 'SOLO_ROSETAS',
    etiqueta: 'Sólo rosetas (clase 85)',
    hint: '17.348 rosetas. No aparecen en los recorridos de camino óptico —el recorrido termina en la caja PON— pero la colección existe. ~17 min.',
    usaClasesBotella: false,
  },
  {
    valor: 'SOLO_CABLES',
    etiqueta: 'Sólo cables FO (clase 51)',
    hint: '~33.100 cables FO, sin botellas. Al terminar da de baja los cables que Cromo borró (cada uno se confirma contra Cromo) y retira sus asignaciones de servicio. ~10 min.',
    usaClasesBotella: false,
  },
  {
    valor: 'SOLO_CABLES_BAJADA',
    etiqueta: 'Sólo cables de bajada (clase 66)',
    hint: '19.030 cables de bajada. Van a la misma tabla que los de FO, distinguidos por clase. ~16 min.',
    usaClasesBotella: false,
  },
  {
    valor: 'SOLO_CABLES_TERCEROS',
    etiqueta: 'Sólo cables de terceros (clases 52, 59, 60)',
    hint: '~733 cables de terceros (52 varios, 59 Telefónica, 60 Telecom) con sus tubos y pelos, y después el matching de servicios. También corren dentro de la Completa. ~4 min.',
    usaClasesBotella: false,
  },
];

export type CromoModoIngesta = (typeof CROMO_MODOS_INGESTA_INFO)[number]['valor'];

export async function iniciarIngestaCromo(opciones: {
  psize: CromoPsize;
  maxPaginas: number | null;
  clases: number[];
  modo?: CromoModoIngesta;
}): Promise<{ corrida_id: number }> {
  return requestJson('/api/admin/ingesta/cromo', {
    method: 'POST',
    json: {
      psize: opciones.psize,
      max_paginas: opciones.maxPaginas,
      clases: opciones.clases,
      modo: opciones.modo ?? 'COMPLETA',
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
