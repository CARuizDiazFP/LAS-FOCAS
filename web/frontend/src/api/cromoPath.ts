// Nombre de archivo: cromoPath.ts
// Ubicación de archivo: web/frontend/src/api/cromoPath.ts
// Descripción: Cliente frontend del camino óptico de Cromo — semillas, resolución del recorrido con su auditoría, y descarga del tracking .txt

import { requestDownload, requestJson } from './client';

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
  | 'ODF_NODO'
  | 'FUSION_ODF'
  | string;

export type TipoInconsistencia = 'DISCREPA' | 'NO_INGERIDO';

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
  /**
   * Cuántos caminos (y `.txt`) tiene el Servicio según la regla de operaciones: tantos como pelos
   * del Servicio en un mismo cable u ODF. Cuáles son los resuelve `resolverCaminosServicio`.
   */
  caminos_esperados?: number;
  /** Pelos que se sacaron del Servicio en local (huérfanos excluidos). */
  excluidos?: PeloExcluido[];
  /**
   * Hay posiciones de ODF con pelo (o una declarada vigente) con las que resolver aunque no haya
   * semillas etiquetadas (el 93150 va por pelos con la etiqueta 44649). Viene acá porque el
   * endpoint de posiciones es admin: un no admin no tiene otra forma de saberlo.
   */
  tiene_posiciones?: boolean;
}

export interface PeloExcluido {
  pelo_n_id: number;
  numero_pelo: string | null;
  color: string | null;
  cable_nombre: string | null;
  motivo: string | null;
  excluido_por: string | null;
  created_at: string | null;
  /** MANUAL (desde este panel) | AUDITORIA (Normalizar en el Viewer de huérfanos). */
  origen?: string;
}

/** Extremo de un camino: dónde empieza o termina su `.txt` (conector de ODF o un pelo). */
export interface ExtremoCamino {
  tipo: string;
  id_cromo: number;
  odf_n_id: number | null;
  odf_nombre: string | null;
  /** 69 = ODF, 86 = ODF Nodo. */
  odf_clase: number | null;
  patchera_nombre: string | null;
  conector: string | null;
}

export interface ExtremosCamino {
  a: ExtremoCamino | null;
  b: ExtremoCamino | null;
}

/** ODF que toca un camino (extremo o intermedia), ya con el `n_id` de linaje. */
export interface OdfDeCamino {
  odf_n_id: number;
  odf_nombre: string | null;
  /** 69 = ODF, 86 = ODF Nodo; `null` si no está ingerida y no es extremo. */
  odf_clase: number | null;
}

/** `VIGENTE`: el camino sale de una posición vigente declarada; `TRAMO`: lo calculó el motor. */
export type RolCamino = 'VIGENTE' | 'TRAMO';

/** Camino que es un tramo del Servicio: tiene su propio `.txt` (`{at62} CROMO T{n} pelo {n_id}.txt`). */
export interface TramoDelServicio {
  /** Número de tramo, el mismo que lleva el nombre del archivo. */
  n: number;
  /** Pelo con el que se generó el camino: es el que se pide para bajar su `.txt`. */
  pelo_n_id: number;
  nombre_archivo: string;
  desde_cache: boolean;
  pelos_en_camino: number;
  extremos: ExtremosCamino;
  /** Todas las ODF que toca el camino, extremos e intermedias. */
  odfs: OdfDeCamino[];
  /** Opcional por compatibilidad con un backend anterior a la posición vigente. */
  rol?: RolCamino;
  /** ODF en los dos extremos. */
  completo?: boolean;
}

/** Camino que no es un tramo del Servicio: no se descarga. */
export interface CaminoResidual {
  pelo_n_id: number;
  nombre_archivo: string;
  pelos_en_camino: number;
  extremos: ExtremosCamino;
  /** Todas las ODF que toca el camino: un residual puede ser la única vía a una ODF del Servicio. */
  odfs: OdfDeCamino[];
}

/**
 * Camino completo que Cromo también documenta para el Servicio pero que no es vigente ni tramo:
 * tiene `.txt` propio (`{servicio} CROMO A{n} pelo {n_id}.txt`, lo baja `track N full`) y
 * "Descargar todos" no lo incluye.
 */
export interface CaminoAdicional extends CaminoResidual {
  /** Número de adicional, el mismo que lleva el nombre del archivo (`A{n}`). */
  n: number;
  desde_cache: boolean;
  completo: boolean;
  /** De dónde salió: una posición declarada, un pelo etiquetado o una posición posible. */
  origen: 'DECLARADO' | 'ETIQUETADO' | 'POSICION' | null;
  /** Posiciones de ODF del camino ("O-1239922-1:1"), vacío si no tiene. */
  posiciones: string;
  /** Etiquetas (`at.61`) de sus pelos. */
  etiquetas: string[];
}

/** Aviso de una posición vigente declarada al resolver los caminos (y si la corrida la retiró). */
export interface AvisoPosicion {
  conector_n_id: number;
  posicion?: string;
  /** `SIN_PELO`, `PELO_CAMBIO`, `CONECTOR_INEXISTENTE`, `PELO_DANADO`, … */
  codigo: string;
  retirada: boolean;
  texto: string;
}

/** Cómo se aplicó la posición vigente declarada en la última resolución de caminos. */
export interface EstadoPosicionCaminos {
  declarada: boolean;
  aplicada: boolean;
  /** "O-1252871-1:1,2", o vacío si no hay declarada. */
  posiciones: string;
  avisos: AvisoPosicion[];
}

/** Conector de ODF que puede ser posición vigente del Servicio (selector del panel). */
export interface PosicionPosible {
  conector_n_id: number;
  /** "O-1252871-1:1". */
  posicion: string;
  odf_n_id: number | null;
  odf_nombre: string | null;
  /** 69 = ODF, 86 = ODF Nodo. */
  odf_clase: number | null;
  bandeja_n_id: number | null;
  bandeja_nombre: string | null;
  numero_conector: string | null;
  /** `null`: el conector no tiene pelo, no se puede declarar. */
  pelo_n_id: number | null;
  numero_pelo: string | null;
  pelos_candidatos: number[];
  cable_n_id: number | null;
  cable_nombre: string | null;
  /** `at.61` del pelo. */
  etiqueta_pelo: string | null;
  /** La etiqueta del pelo es de otro servicio (p. ej. uno de Baja del mismo cliente). */
  etiqueta_ajena: boolean;
  estado_pelo: string | null;
  servicio_resuelto: string | null;
  servicio_id_historico: string | null;
  patch_conector_n_id: number | null;
  por_resuelto: boolean;
  por_pelo: boolean;
  /** Número de otro servicio Activo cuyo pelo también matchea, o `null`. */
  servicio_activo_ajeno: string | null;
  /** El otro hilo del par (mismo cable, conector contiguo), para declararlos juntos. */
  par_sugerido_n_id: number | null;
  declarada: boolean;
}

/** Posición vigente declarada. `valida`/`aviso` dicen si el inventario ingerido todavía la sostiene. */
export interface PosicionDeclarada {
  id: number;
  conector_n_id: number;
  posicion: string;
  odf_n_id: number | null;
  odf_nombre: string | null;
  bandeja_n_id: number | null;
  bandeja_nombre: string | null;
  numero_conector: string | null;
  pelo_n_id_declarado: number | null;
  pelo_n_id_actual: number | null;
  pelos_candidatos: number[];
  declarado_por: string | null;
  declarado_en: string | null;
  valida: boolean;
  aviso: string | null;
  codigo_aviso: string | null;
}

export interface PosicionVigenteResponse {
  declaradas: PosicionDeclarada[];
  posibles: PosicionPosible[];
}

export type RolOdfConfirmada = 'EXTREMO' | 'TRANSITO';

/** ODF que un admin confirmó como parte del recorrido del Servicio. */
export interface OdfConfirmada {
  odf_n_id: number;
  rol: RolOdfConfirmada;
  odf_nombre: string | null;
  /** `ODF` u `ODF_NODO` (`cromo_odfs.tipo_elemento`); `null` si la ODF no está ingerida. */
  odf_tipo: string | null;
  confirmado_por?: string;
  confirmado_en?: string | null;
}

export interface CaminosServicioResponse {
  tramos: TramoDelServicio[];
  residuales: CaminoResidual[];
  /** Trackings esperados que declaró el operador en LAS-FOCAS (no es un dato de Cromo), o `null`. */
  esperados_declarados: number | null;
  /** ODF confirmadas vigentes del Servicio. */
  odf_confirmadas: OdfConfirmada[];
  /** `false` si se cortó el recorrido: por el tope de consultas o por demasiadas semillas fallidas. */
  completo: boolean;
  errores: string[];
  /** Semillas que no quedaron en ningún camino (fallaron o no se llegaron a pedir). */
  no_cubiertos: number;
  /** `true` sólo si el corte fue por el tope de consultas a Cromo. */
  tope_llamadas: boolean;
  /** Segmentos físicos: grupos de tramos que comparten cables (un par de hilos es uno). */
  segmentos: number;
  /** Casos de inconsistencias de Cromo que tocan al Servicio (aviso del panel). */
  inconsistencias?: ResumenInconsistenciasServicio;
  // Opcionales por compatibilidad con un backend anterior a la posición vigente.
  /** Caminos completos que no son vigentes ni tramos: con `.txt` propio, fuera de "Descargar todos". */
  adicionales?: CaminoAdicional[];
  /** Tramos + adicionales: lo que baja `track N full`. */
  caminos_resueltos?: number;
  posicion_vigente?: EstadoPosicionCaminos;
}

/** Casos de inconsistencias de Cromo del Servicio: en cuarentena (no cuentan como uso) y en revisión. */
export interface ResumenInconsistenciasServicio {
  cuarentena: number;
  en_revision: number;
}


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
  opciones: {
    peloNId?: number | null;
    tramo?: number | null;
    adicional?: number | null;
    signal?: AbortSignal;
  } = {},
): Promise<string> {
  const params = new URLSearchParams();
  if (opciones.peloNId != null) {
    params.set('pelo_n_id', String(opciones.peloNId));
  }
  // El número de tramo (o de adicional) hace que el archivo se llame igual que el que sube Slack.
  // Son excluyentes: el backend responde 400 si llegan los dos.
  if (opciones.tramo != null) {
    params.set('tramo', String(opciones.tramo));
  } else if (opciones.adicional != null) {
    params.set('adicional', String(opciones.adicional));
  }
  const query = params.toString();
  return requestDownload(
    `/api/infra/cromo/servicios/${servicioId}/camino-optico/tracking.txt${query ? `?${query}` : ''}`,
    { fallbackFilename: `tracking_cromo_servicio_${servicioId}.txt`, signal: opciones.signal },
  );
}

/**
 * Resuelve los caminos del Servicio en el backend: los caminos del Servicio separados en tramos (con
 * su `.txt`) y residuales (sin él). Mismo criterio que `@bot track` en Slack.
 *
 * **Va a Cromo** (4,6-14 s por camino en frío) y deja cacheado cada tracking, así que bajar los
 * `.txt` después es inmediato. Sin timeout propio del cliente: con 2 caminos en frío puede pasar
 * los 30 s del camino individual, y cortarlo sólo haría perder lo que ya se resolvió.
 */
export async function resolverCaminosServicio(
  servicioId: number,
  opciones: { signal?: AbortSignal } = {},
): Promise<CaminosServicioResponse> {
  return requestJson<CaminosServicioResponse>(
    `/api/infra/cromo/servicios/${servicioId}/camino-optico/caminos`,
    { signal: opciones.signal },
  );
}

/** Devuelve al Servicio un pelo excluido. Admin. */
export async function restaurarPeloServicio(
  servicioId: number,
  peloNId: number,
): Promise<{ ok: boolean; pelo_n_id: number }> {
  return requestJson(`/api/admin/infra/servicios-odf/${servicioId}/pelos-excluidos/restaurar`, {
    method: 'POST',
    json: { pelo_n_id: peloNId },
    csrf: true,
  });
}

/** Confirma ODF del Servicio en lote (un camino que termina en una ODF confirmada y no es ruido chico es tramo). Admin. */
export async function confirmarOdfsServicio(
  servicioId: number,
  odfs: { odf_n_id: number; rol: RolOdfConfirmada }[],
): Promise<{ ok: boolean; odf_confirmadas: OdfConfirmada[] }> {
  return requestJson(`/api/admin/infra/servicios-odf/${servicioId}/odf-confirmadas`, {
    method: 'POST',
    json: { odfs },
    csrf: true,
  });
}

/** Quita la confirmación de una ODF (el historial queda). Admin. */
export async function desconfirmarOdfServicio(
  servicioId: number,
  odfNId: number,
): Promise<{ ok: boolean; odf_confirmadas: OdfConfirmada[] }> {
  return requestJson(
    `/api/admin/infra/servicios-odf/${servicioId}/odf-confirmadas/desconfirmar`,
    { method: 'POST', json: { odf_n_id: odfNId }, csrf: true },
  );
}

/**
 * Posiciones vigentes declaradas del Servicio y las posibles para el selector. SQL local: no toca
 * Cromo ni retira nada (retirar es efecto de la resolución de caminos). Admin.
 */
export async function obtenerPosicionVigente(servicioId: number): Promise<PosicionVigenteResponse> {
  return requestJson<PosicionVigenteResponse>(
    `/api/admin/infra/servicios-odf/${servicioId}/posicion-vigente`,
  );
}

/**
 * Declara conectores de ODF como posición vigente del Servicio (todo o nada, 1 a 8; los ya
 * vigentes quedan). 409 si alguno no es posición posible o no tiene pelo. Admin.
 */
export async function declararPosicionVigente(
  servicioId: number,
  conectoresNId: number[],
): Promise<{ ok: boolean; declaradas: PosicionDeclarada[] }> {
  return requestJson(`/api/admin/infra/servicios-odf/${servicioId}/posicion-vigente`, {
    method: 'POST',
    json: { conectores_n_id: conectoresNId },
    csrf: true,
  });
}

/** Retira a mano la posición vigente de un conector (el historial queda). Admin. */
export async function retirarPosicionVigente(
  servicioId: number,
  conectorNId: number,
): Promise<{ ok: boolean; declaradas: PosicionDeclarada[] }> {
  return requestJson(`/api/admin/infra/servicios-odf/${servicioId}/posicion-vigente/retirar`, {
    method: 'POST',
    json: { conector_n_id: conectorNId },
    csrf: true,
  });
}

/** Declara cuántos trackings espera el Servicio; `null` borra la declaración. Admin. */
export async function declararTrackingsEsperados(
  servicioId: number,
  cantidad: number | null,
): Promise<{ ok: boolean; trackings_esperados: number | null }> {
  return requestJson(`/api/admin/infra/servicios-odf/${servicioId}/trackings-esperados`, {
    method: 'POST',
    json: { cantidad },
    csrf: true,
  });
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
