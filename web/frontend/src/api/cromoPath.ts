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
  // Red de acceso PON. Aparecen sólo cuando el camino se siembra desde una salida del splitter,
  // hacia el extremo cliente: desde el lado de red el recorrido se corta en el splitter.
  | 'SPLITTER'
  | 'PUERTO_SPLITTER'
  | 'CAJA_PON'
  | 'CABLE_BAJADA'
  | 'NODO'
  | 'FUSION_ODF'
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
  SPLITTER: 'Splitter',
  PUERTO_SPLITTER: 'Puerto de splitter',
  CAJA_PON: 'Caja PON',
  CABLE_BAJADA: 'Cable de bajada',
  NODO: 'Nodo',
  FUSION_ODF: 'Fusión en ODF',
  ROSETA: 'Roseta',
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
  SPLITTER: 'ph-share-network',
  PUERTO_SPLITTER: 'ph-arrow-elbow-down-right',
  CAJA_PON: 'ph-package',
  CABLE_BAJADA: 'ph-line-segment',
  NODO: 'ph-buildings',
  FUSION_ODF: 'ph-arrows-merge',
  ROSETA: 'ph-house-line',
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
  /**
   * Cuándo se generó el tracking cacheado de este pelo (ISO), o `null` si no hay uno fresco.
   * Sirve para avisarle al operador si la descarga es instantánea o si va a pagar los 4,6-14 s
   * que cuesta resolver el camino contra Cromo.
   */
  tracking_en_cache: string | null;
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
  /** Ratio del splitter tal como lo PUBLICA Cromo en `at.83` ("1x8", "1x4"). No es una inferencia
   * por fan-out: es dato. */
  splitter_ratio: string | null;
  splitter_nombre: string | null;
  splitter_id: number | null;
  /** Cantidad de salidas reales del splitter, de `splitter_a.c_out`. */
  splitter_salidas: number | null;
  puerto_nombre: string | null;
  puerto_sentido: string | null;
  /** "Aereo" / "Subsuelo" / "Canalizado", en cables de bajada y cajas PON. */
  tendido: string | null;
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
  /** La red de acceso PON se cuenta aparte: sumar un cable de bajada a la troncal distorsionaría
   * la longitud óptica del backbone. */
  splitters: number;
  cajas_pon: number;
  cables_bajada: number;
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
  /**
   * Pelos a tildar por defecto: las posiciones de ODF asociadas al Servicio, que pueden ser más
   * de una. Si la ODF todavía no fue relevada cae al primer pelo del ranking.
   */
  preseleccionados: number[];
  /** `false` cuando ninguna semilla tiene conector de ODF ingerido: hay que relevar la ODF. */
  odf_relevada: boolean;
  /**
   * Universo real de pelos matcheados al Servicio, **sin** el tope que trunca `pelos`. Es grande
   * por diseño: el número de servicio viaja en el `at.61` de todos los pelos del recorrido, no
   * sólo de los extremos (medido: 227 para el Servicio 93154).
   */
  total_matcheados: number;
  /** Cuántos de esos son posición de patchera: los que el operador llama "los pelos del Servicio"
   * (2 en el Servicio 93154, contra 227 matcheados). */
  total_con_posicion_odf: number;
}

// ── Llamadas ──────────────────────────────────────────────────────────────

/** Semillas de un Servicio. SQL local: no toca Cromo, así se puede pedir en la carga de la vista. */
export async function listarPelosCamino(
  servicioId: number,
  opciones: { priorizarConector?: boolean } = {},
): Promise<PelosCaminoResponse> {
  // `priorizarConector` invierte el ranking del backend para poner primero las posiciones de ODF.
  // Hace falta pedirlo explícitamente porque la lista viene truncada: con el orden por defecto
  // —pensado para DESCUBRIR ODFs nuevas— los pelos que son posición de ODF quedan al final y, en
  // un Servicio con cientos de pelos matcheados, fuera del tope.
  const query = opciones.priorizarConector ? '?priorizar_conector=true' : '';
  return requestJson<PelosCaminoResponse>(
    `/api/infra/cromo/servicios/${servicioId}/camino-optico/pelos${query}`,
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

// ── Normalización de la consistencia y relevamiento de ODF ─────────────────

export interface ItemNormalizado {
  elemento_id: number;
  regla: string;
  accion: string;
  detalle: string | null;
}

export interface NormalizarConsistenciaResponse {
  ok: boolean;
  corrida_id: number | null;
  pelo_n_id: number;
  creados: number;
  actualizados: number;
  sin_cambios: number;
  errores: number;
  total_discrepa_previo: number;
  total_no_ingerido_previo: number;
  detalle: ItemNormalizado[];
}

/**
 * Normaliza las discrepancias de la auditoría tomando **Cromo como referencia**: el backend vuelve
 * a traer de Cromo el objeto real y lo reingiere por el mismo parser y los mismos upserts que la
 * ingesta regular, con su corrida sintética auditable.
 *
 * Cuesta una llamada a Cromo por objeto más la resolución del camino, así que es lenta a
 * propósito: no hay una vía rápida que no implique escribir inventario a ciegas.
 *
 * `elementoIds` acota qué corregir; sin él se normaliza todo lo inconsistente. En los dos casos el
 * backend recalcula qué está realmente mal: no confía en esta lista para decidir qué escribir.
 */
export async function normalizarConsistencia(
  servicioId: number,
  peloNId: number,
  opciones: { elementoIds?: number[]; signal?: AbortSignal } = {},
): Promise<NormalizarConsistenciaResponse> {
  return requestJson<NormalizarConsistenciaResponse>(
    `/api/admin/infra/servicios-odf/${servicioId}/camino-optico/normalizar`,
    {
      method: 'POST',
      json: { pelo_n_id: peloNId, elemento_ids: opciones.elementoIds ?? null },
      csrf: true,
      signal: opciones.signal,
    },
  );
}

export interface RelevarOdfResponse {
  ok: boolean;
  corrida_id: number | null;
  relevadas: number;
  errores: number;
  detalle: { odf_n_id: number; accion: string; detalle: string | null }[];
}

/**
 * Releva las ODFs que atraviesa el camino del pelo, poblando sus posiciones de patchera.
 * Es lo que destraba la preselección de posiciones de ODF para descargar los trackings.
 */
export async function relevarOdfsDelCamino(
  servicioId: number,
  peloNId: number,
  opciones: { odfsNId?: number[]; signal?: AbortSignal } = {},
): Promise<RelevarOdfResponse> {
  return requestJson<RelevarOdfResponse>(
    `/api/admin/infra/servicios-odf/${servicioId}/camino-optico/relevar-odf`,
    {
      method: 'POST',
      json: { pelo_n_id: peloNId, odfs_n_id: opciones.odfsNId ?? null },
      csrf: true,
      signal: opciones.signal,
    },
  );
}
