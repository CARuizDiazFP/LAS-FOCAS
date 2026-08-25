// Nombre de archivo: botellas.ts
// Ubicación de archivo: web/frontend/src/api/botellas.ts
// Descripción: Cliente frontend para el listado unificado de Botellas (Cromo + legado Infra/Baneos), el dashboard admin Viewer y la detección/apropiación de duplicados

import { requestJson } from './client';

export type BotellaOrigen = 'cromo' | 'legado';

export interface BotellaUnificadaItem {
  origen: BotellaOrigen;
  id: number;
  nombre: string | null;
  estado: string | null;
}

export interface SearchBotellasResponse {
  total: number;
  limit: number;
  offset: number;
  botellas: BotellaUnificadaItem[];
}

export interface SearchBotellasParams {
  q?: string;
  limit?: number;
  offset?: number;
  incluirNoOperativas?: boolean;
}

const PARAM_KEY_MAP: Record<string, string> = { incluirNoOperativas: 'incluir_no_operativas' };

export type EstadoBotellaToken = 'ok' | 'warn' | 'error' | 'idle';

export function estadoBotellaToken(estado: string | null | undefined): EstadoBotellaToken {
  const value = (estado ?? '').trim().toUpperCase();
  if (value === 'LIBRE') return 'ok';
  if (value === 'OCUPADA') return 'warn';
  if (value === 'BANEADA') return 'error';
  return 'idle';
}

// `object` y no `Record<string, ...>`: las interfaces de params de este archivo no declaran index
// signature, así que no son asignables a un Record — pero sí a `object`, que es lo único que
// `Object.entries` necesita.
function toQuery(params: object): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    // `false` se omite a propósito además de undefined/null/'': el default del backend ya es
    // `incluir_no_operativas=false`, no hace falta viajarlo cuando el toggle está apagado.
    if (value === undefined || value === null || value === '' || value === false) return;
    query.set(PARAM_KEY_MAP[key] ?? key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

export async function searchBotellas(params: SearchBotellasParams): Promise<SearchBotellasResponse> {
  return requestJson<SearchBotellasResponse>(`/api/infra/botellas/buscar${toQuery(params)}`);
}

// Estados operables vigentes (2026-08-11): LIBRE/OCUPADA/BANEADA/NO_OPERATIVA — mismo vocabulario
// que `estados_disponibles` de `GET /api/infra/camaras/{id}/estado`.
export type EstadoBotellaValor = 'NO_OPERATIVA' | 'LIBRE' | 'OCUPADA' | 'BANEADA';

export interface BotellaClave {
  origen: BotellaOrigen;
  id: number;
}

export interface BotellasEstadoMasivoResponse {
  ok: boolean;
  estado_nuevo: string;
  legado_actualizadas: number;
  cromo_actualizadas: number;
  no_encontrados: BotellaClave[];
}

/** Cambia el estado de un lote de Botellas (Cromo + legado) en una sola operación — clave siempre
 * compuesta `{origen, id}`, nunca un id numérico solo. Ver `PUT /api/infra/botellas/estado`. */
export async function updateBotellasEstadoMasivo(
  items: BotellaClave[],
  estado: EstadoBotellaValor,
): Promise<BotellasEstadoMasivoResponse> {
  return requestJson<BotellasEstadoMasivoResponse>('/api/infra/botellas/estado', {
    method: 'PUT',
    json: { items: items.map((item) => ({ origen: item.origen, id: item.id })), estado },
    csrf: true,
  });
}

export interface CromoBotellaEstadoAsociacion {
  n_id: number;
  nombre: string | null;
  huerfana: boolean;
  camara_id: number | null;
  camara_nombre: string | null;
}

/** Estado de asociación de una Botella Cromo puntual — huérfana, o Cámara padre vinculada
 * (`camara_id`/`camara_nombre`, 2026-08-13) para la navegación cruzada hacia `CamaraDetailView`. */
export async function getCromoBotellaEstadoAsociacion(nId: number): Promise<CromoBotellaEstadoAsociacion> {
  return requestJson<CromoBotellaEstadoAsociacion>(`/api/infra/cromo-botellas/${nId}/estado-asociacion`);
}

/** Listado paginado dual para `/admin/servicios/viewer/Botellas` — mismo shape que `searchBotellas`,
 * con guarda admin adicional (`GET /api/admin/infra/botellas/viewer`). */
export async function getBotellasViewer(params: SearchBotellasParams): Promise<SearchBotellasResponse> {
  return requestJson<SearchBotellasResponse>(`/api/admin/infra/botellas/viewer${toQuery(params)}`);
}

export interface BotellaDuplicadaItem {
  origen: BotellaOrigen;
  id: number;
  nombre: string;
  estado: string;
  // Señal "operativa" (tiene al menos un cable asociado) — sólo calculada para origen='cromo';
  // `null` para 'legado', donde esa señal no existe (ver tiene_cables_asociados_batch_sync).
  tiene_cables: boolean | null;
}

export interface GrupoBotellasDuplicadas {
  camara_padre_id: number;
  camara_padre_nombre: string;
  clave_normalizada: string;
  criterio: string;
  estados_en_conflicto: boolean;
  estado_mas_restrictivo: string;
  resoluble: boolean;
  miembros: BotellaDuplicadaItem[];
}

export interface BotellasDuplicadosResponse {
  total_grupos: number;
  grupos: GrupoBotellasDuplicadas[];
}

export interface BotellasDuplicadosParams {
  /** `true` saltea la caché Redis del backend y fuerza el recálculo síncrono. Sólo para el botón
   * "Actualizar" — es la escotilla manual para cuando algo cambió por fuera de los 8 mutadores que
   * invalidan la caché (ingesta Cromo, baneos/estados, merge/eliminar Cámaras, backfill,
   * eliminar-grupo). */
  refrescar?: boolean;
}

/** Grupos de Botellas candidatas a duplicado dentro de la misma Cámara padre (sin paginar). */
export async function getBotellasDuplicados(
  params: BotellasDuplicadosParams = {},
): Promise<BotellasDuplicadosResponse> {
  return requestJson<BotellasDuplicadosResponse>(
    `/api/admin/infra/botellas/viewer/duplicados${toQuery(params)}`,
  );
}

export interface ApropiarBotellaResponse {
  ok: boolean;
  legado_id: number;
  legado_nombre: string;
  cromo_n_id: number;
  cromo_nombre: string | null;
  camara_padre_id: number;
  camara_padre_nombre: string;
  botellas_legado_migradas: number;
  cromo_reasignadas: number;
  cables_migrados: number;
  empalmes_migrados: number;
  ingresos_migrados: number;
  aliases_migrados: number;
  estado_final: string;
}

/** Apropia una Botella legado hacia su CromoBotella hermana (mismo padre) — Cromo se conserva, la
 * legado se elimina tras reasignar sus datos reales a la Cámara padre compartida. */
export async function apropiarBotellaLegadoACromo(legadoId: number, cromoNId: number): Promise<ApropiarBotellaResponse> {
  return requestJson<ApropiarBotellaResponse>('/api/infra/botellas/apropiar', {
    method: 'POST',
    json: { legado_id: legadoId, cromo_n_id: cromoNId },
    csrf: true,
  });
}

export interface ApropiarMasivoDetalleItem {
  exito: boolean;
  legado_id: number;
  cromo_n_id: number;
  camara_padre_nombre: string;
  estado_final?: string;
  error?: string;
}

export interface ApropiarMasivoResponse {
  ok: boolean;
  total_grupos: number;
  grupos_resolubles: number;
  grupos_apropiados: number;
  grupos_con_error: number;
  detalle: ApropiarMasivoDetalleItem[];
}

/** Apropia automáticamente TODOS los grupos de Botellas duplicadas resolubles (1 legado + 1 Cromo
 * por padre) — cada grupo corre en su propia transacción, ver `POST /api/infra/botellas/apropiar-masivo`. */
export async function apropiarMasivoBotellas(): Promise<ApropiarMasivoResponse> {
  return requestJson<ApropiarMasivoResponse>('/api/infra/botellas/apropiar-masivo', {
    method: 'POST',
    json: {},
    csrf: true,
  });
}

// ── Consolidación manual de duplicados Cromo (grupo libre) ──────────────────
// Cierra el gap "Revisión manual" (2+ Cromo, 2+ legado, mixtos) — a diferencia de `apropiar*`, no
// está restringido a un grupo detectado por nombre normalizado: los orígenes pueden tipearse a mano
// (cubre botellas sin nombre, que el detector nunca agrupa).

export interface ConsolidarBotellasPayload {
  idsOrigenCromo: number[];
  idDestinoCromo: number;
  idsLegado?: number[];
  nombreDestino?: string | null;
  motivo?: string | null;
  /** Bypasea el guard de "misma Cámara padre" de `apropiar_legado_a_cromo` para las
   * `idsLegado` incluidas — no afecta `idsOrigenCromo` (Cromo↔Cromo no tiene ese guard). */
  forceCameraAssociation?: boolean;
}

export interface AliasRepuntadoItem {
  origen: number;
  destino_anterior: number | null;
  destino_nuevo: number;
}

export interface ConsolidarBotellasResponse {
  ok: boolean;
  id_destino_cromo: number;
  alias_creados: number;
  alias_actualizados: number;
  alias_repuntados: AliasRepuntadoItem[];
  alias_dependientes_recableados: number;
  cables_existentes_recableados: number;
  fusiones_existentes_recableadas: number;
  legados_migrados: number[];
  cables_migrados: number;
  empalmes_migrados: number;
  ingresos_migrados: number;
  camara_aliases_migrados: number;
  nombre_anterior: string | null;
  nombre_nuevo: string | null;
  legados_con_camara_forzada: number[];
}

/** Consolida un grupo libre de n_ids Cromo hacia un único destino — ver `POST
 * /api/infra/botellas/consolidar`. */
export async function consolidarBotellasCromo(
  payload: ConsolidarBotellasPayload,
): Promise<ConsolidarBotellasResponse> {
  return requestJson<ConsolidarBotellasResponse>('/api/infra/botellas/consolidar', {
    method: 'POST',
    json: {
      ids_origen_cromo: payload.idsOrigenCromo,
      id_destino_cromo: payload.idDestinoCromo,
      ids_legado: payload.idsLegado ?? [],
      nombre_destino: payload.nombreDestino ?? null,
      motivo: payload.motivo ?? null,
      force_camera_association: payload.forceCameraAssociation ?? false,
    },
    csrf: true,
  });
}

/** Cuáles de los n_ids Cromo dados tienen cables asociados — para IDs tipeados a mano que no vienen
 * de un grupo ya detectado (ese caso ya trae `tiene_cables` en `BotellaDuplicadaItem`). */
export async function getBotellasOperatividad(nIds: number[]): Promise<number[]> {
  const data = await requestJson<{ operativos: number[] }>('/api/admin/infra/botellas/operatividad', {
    method: 'POST',
    json: { n_ids: nIds },
  });
  return data.operativos;
}

/** Path del export de inconsistencias (huérfanas + duplicados no resolubles) — GET simple, la sesión
 * viaja por cookie, sin CSRF (no es mutación). Usar en un `<a href>`/`window.open`. */
export function exportarBotellasInconsistenciasUrl(): string {
  return '/api/admin/infra/botellas/inconsistencias/exportar';
}

// ── Eliminación permanente de una Botella genuinamente vacía ────────────────
// Se rechaza si tiene Cables/Empalmes/Ingresos (legado) o Cables/Fusiones Cromo asociados, o si
// (Cromo) ya es destino de otra fila de alias. Ver POST /api/infra/botellas/eliminar.

export interface BloqueoEliminacion {
  origen: 'legado' | 'cromo' | 'camara';
  id: number;
  nombre: string | null;
  razon: string;
}

export interface EliminarBotellaResponse {
  ok: boolean;
  origen: BotellaOrigen;
  id: number;
  camara_padre_eliminada: number | null;
  alias_registrado: boolean;
}

export async function eliminarBotella(origen: BotellaOrigen, id: number): Promise<EliminarBotellaResponse> {
  return requestJson<EliminarBotellaResponse>('/api/infra/botellas/eliminar', {
    method: 'POST',
    json: { origen, id },
    csrf: true,
  });
}

// ── "Borrar y Excluir Cromo" — borrado forzado de un grupo completo ─────────
// A diferencia de eliminarBotella, NUNCA bloquea por Cables/Fusiones reales asociados — es el
// camino deliberado para el botón de grupo del visor de duplicados. Ver POST
// /api/infra/botellas/eliminar-grupo.

export interface EliminarGrupoCromoResponse {
  ok: boolean;
  botellas_eliminadas: number[];
  cables_eliminados: number;
  fusiones_eliminadas: number;
  aliases_registrados: number;
  no_encontradas: number[];
}

export async function eliminarGrupoCromo(idsCromo: number[]): Promise<EliminarGrupoCromoResponse> {
  return requestJson<EliminarGrupoCromoResponse>('/api/infra/botellas/eliminar-grupo', {
    method: 'POST',
    json: { ids_cromo: idsCromo },
    csrf: true,
  });
}

// ── Repoblar Cables / editar nombre (Verificador Cromo, sólo admin) ──────────
// Ver `detectarCablesCromo` (api/cromo.ts) para la detección de sólo lectura que alimenta el botón
// "Repoblar Cables". Ninguna de las dos escribe hacia Cromo — sólo actualizan la base local.

export interface RepoblarCablesItemResultado {
  n_id: number;
  accion: 'CREADA' | 'ACTUALIZADA' | 'SIN_CAMBIOS' | 'ERROR';
  detalle: string | null;
}

export interface RepoblarCablesResponse {
  ok: boolean;
  corrida_id: number | null;
  botella_n_id: number;
  creados: number;
  actualizados: number;
  sin_cambios: number;
  errores: number;
  detalle: RepoblarCablesItemResultado[];
}

export async function repoblarCablesCromo(botellaNId: number): Promise<RepoblarCablesResponse> {
  return requestJson<RepoblarCablesResponse>(`/api/infra/botellas/${botellaNId}/repoblar-cables`, {
    method: 'POST',
    json: {},
    csrf: true,
  });
}

export interface EditarNombreBotellaResponse {
  ok: boolean;
  /** n_id REAL bajo el que quedó la fila — puede diferir del pedido si el n_id de la URL era un id
   *  de versión y Cromo reportó otro n_id de linaje al crearla desde vivo (caso "ID dual"). */
  n_id: number;
  nombre: string;
  /** Sólo presente cuando `n_id` difiere del que se pidió: el n_id original de la URL. */
  n_id_solicitado?: number;
}

export async function editarNombreBotellaCromo(nId: number, nombre: string): Promise<EditarNombreBotellaResponse> {
  return requestJson<EditarNombreBotellaResponse>(`/api/infra/botellas/${nId}/nombre`, {
    method: 'PATCH',
    json: { nombre },
    csrf: true,
  });
}

export interface SepararBotellaDePadreResponse {
  ok: boolean;
  botella_n_id: number;
  camara_anterior_id: number | null;
  camara_nueva_id: number;
  camara_nueva_nombre: string;
}

export async function separarBotellaDeCamaraPadre(
  nId: number,
  nombre: string,
  motivo: string,
): Promise<SepararBotellaDePadreResponse> {
  return requestJson<SepararBotellaDePadreResponse>(`/api/infra/botellas/${nId}/separar-padre`, {
    method: 'POST',
    json: { nombre, motivo },
    csrf: true,
  });
}
