// Nombre de archivo: cromoPath.ts
// Ubicación de archivo: web/frontend/src/api/cromoPath.ts
// Descripción: Cliente frontend del camino óptico de Cromo — semillas, resolución del recorrido con su auditoría, y descarga del tracking .txt

import { ApiError, requestDownload, requestJson } from './client';

// ── Vocabulario ───────────────────────────────────────────────────────────
// Mismos literales que `core/services/cromo/camino_optico_service.py`: no se reimplementa la
// taxonomía acá, sólo se calca.

export type EstadoCamino = 'OK' | 'SIN_SEMILLA' | 'SIN_CAMINO';

export type TipoNodoCamino =
  | 'PELO'
  | 'FUSION'
  | 'CONECTOR_ODF'
  | 'NO_RESUELTO'
  | 'CLASE_DESCONOCIDA'
  | string;

export type TipoInconsistencia = 'DISCREPA' | 'NO_INGERIDO';

const TIPO_NODO_LABELS: Record<string, string> = {
  PELO: 'Pelo',
  FUSION: 'Fusión',
  CONECTOR_ODF: 'Conector de ODF',
  NO_RESUELTO: 'No resuelto por Cromo',
  CLASE_DESCONOCIDA: 'Clase desconocida',
  CABLE: 'Cable',
  BOTELLA: 'Botella',
  TUBO: 'Tubo',
  ODF: 'ODF',
  PATCHERA: 'Patchera',
  CAMARA: 'Cámara',
};

/** Ícono Phosphor por tipo de nodo. Deliberadamente NO se usa color: los tipos se distinguen por
 * ícono para no introducir una paleta categórica nueva (ver nocturne-token-compliance). */
const TIPO_NODO_ICONOS: Record<string, string> = {
  PELO: 'ph-line-segment',
  FUSION: 'ph-arrows-merge',
  CONECTOR_ODF: 'ph-plugs-connected',
  NO_RESUELTO: 'ph-warning',
  CABLE: 'ph-line-segment',
  BOTELLA: 'ph-package',
  ODF: 'ph-plugs-connected',
  CAMARA: 'ph-map-pin',
};

export function tipoNodoLabel(tipo: string): string {
  return TIPO_NODO_LABELS[tipo] ?? tipo;
}

export function tipoNodoIcono(tipo: string): string {
  return TIPO_NODO_ICONOS[tipo] ?? 'ph-question';
}

// ── Tipos de la respuesta ─────────────────────────────────────────────────

export interface PeloSemilla {
  pelo_n_id: number;
  servicio_numero: string | null;
  metodo: string | null;
  confianza: number | null;
  numero_pelo: string | null;
  color: string | null;
  cable_n_id: number | null;
  cable_nombre: string | null;
  tiene_conector_odf: boolean;
  /** `at.61` crudo: es el "por qué matcheó" que le permite al operador evaluar la semilla. */
  servicio_raw: string | null;
}

export interface VinculoLocalCamino {
  tabla: string;
  n_id: number;
  nombre: string | null;
  vigente: boolean;
  coincide_por: 'N_ID' | 'VERSION_ID' | string;
}

export interface NodoCamino {
  orden: number;
  lado: 'A' | 'B' | 'RAIZ' | string;
  id_cromo: number;
  clase: number | null;
  tipo: TipoNodoCamino;
  nombre: string | null;
  repetido: boolean;
  numero_pelo: string | null;
  color_pelo: string | null;
  tubo_id: number | null;
  tubo_color: string | null;
  cable_id: number | null;
  cable_nombre: string | null;
  cable_capacidad: string | null;
  distancia_geo_m: number | null;
  distancia_real_m: number | null;
  botella_id: number | null;
  botella_nombre: string | null;
  conector_numero: string | null;
  patchera_nombre: string | null;
  odf_id: number | null;
  odf_nombre: string | null;
  servicio_at62: string | null;
  /** `null` NO es error: puede ser una clase que la ingesta no barre, o un objeto que Cromo movió
   * después de la última corrida. Se pinta como "sólo en Cromo". */
  vinculo_local: VinculoLocalCamino | null;
}

export interface OdfDelCamino {
  odf_id: number;
  nombre: string | null;
  lado: string;
  conector_numero: string | null;
  patchera_nombre: string | null;
  servicio_at62: string | null;
  es_extremo: boolean;
  vinculo_local: VinculoLocalCamino | null;
}

export interface EstadisticasCamino {
  nodos: number;
  pelos: number;
  fusiones: number;
  conectores: number;
  cables: number;
  odfs: number;
  no_resueltos: number;
  longitud_geo_m: number;
  longitud_optica_m: number;
}

export interface ResultadoReglaConsistencia {
  regla: string;
  descripcion: string;
  total: number;
  coincide: number;
  discrepa: number;
  no_ingerido: number;
}

export interface InconsistenciaCamino {
  regla: string;
  elemento_id: number;
  tipo: TipoInconsistencia;
  valor_path: unknown;
  valor_local: unknown;
}

export interface ConsistenciaCamino {
  reglas: ResultadoReglaConsistencia[];
  inconsistencias: InconsistenciaCamino[];
  total_discrepa: number;
  total_no_ingerido: number;
}

export interface DiscrepanciaAt62 {
  at62: string | null;
  at61: string | null;
  numero_regex: string | null;
  veredicto: string;
}

export interface CaminoOpticoResponse {
  estado: EstadoCamino;
  motivo: string | null;
  pelo_n_id: number | null;
  identidad_cromo: {
    id_pedido: number | null;
    id_raiz: number | null;
    raiz_es_mismo_id: boolean;
  };
  servicio_at62: string | null;
  servicio_at61: string | null;
  numero_pelo: string | null;
  color_pelo: string | null;
  cable_id: number | null;
  cable_nombre: string | null;
  raiz: NodoCamino | null;
  lado_a: NodoCamino[];
  lado_b: NodoCamino[];
  odfs: OdfDelCamino[];
  estadisticas: EstadisticasCamino;
  consistencia: ConsistenciaCamino | null;
  discrepancia_at62: DiscrepanciaAt62 | null;
  ids_no_resueltos: number[];
  advertencias: string[];
  duracion_ms: number | null;
  semillas_disponibles: number;
  semillas_alternativas: PeloSemilla[];
  payload_raw: Record<string, unknown> | null;
}

export interface PelosCaminoResponse {
  servicio_id: number;
  total: number;
  pelos: PeloSemilla[];
}

// ── Llamadas ──────────────────────────────────────────────────────────────

/** Semillas de un Servicio. SQL local: no toca Cromo, así se puede pedir en la carga de la vista. */
export async function listarPelosCamino(servicioId: number): Promise<PelosCaminoResponse> {
  return requestJson<PelosCaminoResponse>(
    `/api/infra/cromo/servicios/${servicioId}/camino-optico/pelos`,
  );
}

/**
 * Resuelve el camino óptico de un Servicio. **Costoso**: Cromo resuelve el grafo en memoria y
 * tarda ~12 s medidos, así que se llama sólo por acción explícita del operador, nunca al montar
 * una vista ni desde una grilla.
 */
export async function resolverCaminoOptico(
  servicioId: number,
  opciones: { peloNId?: number | null; raw?: boolean; signal?: AbortSignal } = {},
): Promise<CaminoOpticoResponse> {
  const params = new URLSearchParams();
  if (opciones.peloNId != null) {
    params.set('pelo_n_id', String(opciones.peloNId));
  }
  if (opciones.raw) {
    params.set('raw', 'true');
  }
  const query = params.toString();
  return requestJson<CaminoOpticoResponse>(
    `/api/admin/infra/servicios-odf/${servicioId}/camino-optico${query ? `?${query}` : ''}`,
    { signal: opciones.signal },
  );
}

/** Descarga el tracking `.txt` generado desde Cromo. Devuelve el nombre del archivo. */
export async function descargarTrackingCromo(
  servicioId: number,
  opciones: { peloNId?: number | null; signal?: AbortSignal } = {},
): Promise<string> {
  const params = new URLSearchParams();
  if (opciones.peloNId != null) {
    params.set('pelo_n_id', String(opciones.peloNId));
  }
  const query = params.toString();
  return requestDownload(
    `/api/infra/cromo/servicios/${servicioId}/camino-optico/tracking.txt${query ? `?${query}` : ''}`,
    { fallbackFilename: `tracking_cromo_servicio_${servicioId}.txt`, signal: opciones.signal },
  );
}

/**
 * Traduce un error del camino óptico a un mensaje accionable.
 *
 * Los textos de 404/502 son deliberadamente los mismos que ya usa `ModalVerificadorCromo` para
 * que el operador reconozca el mismo error en dos pantallas distintas.
 */
export function mensajeErrorCromoPath(
  error: unknown,
  contexto: { peloNId?: number | null } = {},
): string {
  if (error instanceof DOMException && error.name === 'TimeoutError') {
    return 'Cromo no respondió en 30 s. Podés seguir con la asociación manual: el camino es una señal, no un requisito.';
  }
  if (error instanceof ApiError) {
    if (error.status === 404) {
      const pelo = contexto.peloNId ? ` (pelo ${contexto.peloNId})` : '';
      return `Cromo no conoce este camino${pelo}. Puede haberse dado de baja, o el n_id local quedó desactualizado respecto de Cromo.`;
    }
    if (error.status === 502) {
      return 'Cromo no respondió. Probá de nuevo en un momento.';
    }
    if (error.status === 504 || error.status === 408) {
      return 'El backend cortó la espera de Cromo. El camino puede ser muy largo o Cromo estar saturado — probá de nuevo, o resolvé con otro pelo.';
    }
    if (error.status === 409) {
      return 'Este Servicio no tiene un camino que se pueda resolver: no hay ningún pelo de Cromo asociado.';
    }
    if (error.status === 403) {
      return 'Necesitás rol admin para resolver el camino óptico.';
    }
  }
  return error instanceof Error ? error.message : 'Error resolviendo el camino óptico en Cromo.';
}
