// Nombre de archivo: cromoDetalle.ts
// Ubicación de archivo: web/frontend/src/api/cromoDetalle.ts
// Descripción: Cliente API del detalle de cables y ODFs de Cromo: empalmes, conectores, visor en vivo, validación y cables detectados

import { requestJson } from './client';
import type { CromoServicioEncontrado } from './cromoVerificacion';

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
  /** Prefijo de tipo de servicio extraído de `servicio_raw` por un regex de sólo-display
   * (independiente del que gobierna `tipo_asociacion`/el matching en ingesta) — "-" si no matchea. */
  tipo_servicio: string;
  /** Recicla el match ya resuelto en `servicios[0]` (mismo criterio de "Servicio" previo, renombrado a
   * "Línea") — navegable a `/servicios/ID/{linea}`. `null` si no hay match. */
  linea: string | null;
  cliente: string | null;
  verificable: boolean | null;
  status: string | null;
  fecha_hora_status: string | null;
  /** El pelo es de un caso de inconsistencia de Cromo en CUARENTENA: `servicios` viene vacío
   * porque su uso no cuenta, pero no está libre — se muestra "en cuarentena (inconsistencia Cromo)". */
  en_cuarentena: boolean;
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

// ── Empalmes (fusiones) internos de una Botella ──────────────────────────────
// Vista dedicada `/infra/cromo/verificador/empalmes?n_id=...` (distinta de la tarjeta "Cables
// asociados" del Verificador) — ver `core/services/cromo/empalmes.py` para la lógica de armado y
// agrupación de Splitters (no es una clase Cromo propia, se detecta por un mismo pelo repetido en
// 2+ fusiones de la misma botella).

export interface CromoPeloEmpalme {
  n_id: number;
  cable_n_id: number | null;
  cable_nombre: string | null;
  tubo_n_id: number | null;
  tubo_color: string | null;
  numero_pelo: string | null;
  orden: number | null;
  color: string | null;
  servicio_raw: string | null;
  servicio_numero: string | null;
}

export interface CromoEmpalmeDeBotella {
  fusion_n_id: number;
  nombre_par: string | null;
  es_splitter: boolean;
  pelo_origen: CromoPeloEmpalme | null;
  pelo_destino: CromoPeloEmpalme | null;
  splitter_destinos: CromoPeloEmpalme[];
  splitter_ratio: number | null;
}

export interface CromoCableDeEmpalmes {
  n_id: number;
  nombre: string | null;
  cantidad_empalmes: number;
}

export interface CromoEmpalmesBotella {
  botella_n_id: number;
  nombre: string | null;
  cables: CromoCableDeEmpalmes[];
  empalmes: CromoEmpalmeDeBotella[];
}

export async function obtenerEmpalmesDeBotella(botellaNId: number): Promise<CromoEmpalmesBotella> {
  return requestJson(`/api/infra/cromo/botellas/${botellaNId}/empalmes`);
}

// ── Conectores (posiciones de patchera) de una ODF ───────────────────────────
// Vista dedicada `/infra/cromo/verificador/conectores?n_id=...` (mismo criterio que Empalmes de
// Botella) — ver `core/services/cromo/odf_conectores.py`. `servicio_resuelto` combina el atributo
// directo de Cromo con el regex del pelo (MAX-based ID final); `servicio_id_historico` sólo viene
// poblado cuando ambas señales difieren.

export interface CromoConectorOdf {
  n_id: number;
  bandeja_n_id: number | null;
  bandeja_nombre: string | null;
  numero_conector: string | null;
  pelo_n_id: number | null;
  pelo_numero: string | null;
  servicio_resuelto: string | null;
  servicio_id_historico: string | null;
  servicio_id_externo: string | null;
  nombre_cliente: string | null;
  cliente: string | null;
  estado_servicio: string | null;
}

export interface CromoConectoresOdf {
  odf_n_id: number;
  odf_nombre: string | null;
  conectores: CromoConectorOdf[];
}

export async function obtenerConectoresDeOdf(odfNId: number): Promise<CromoConectoresOdf> {
  return requestJson(`/api/infra/cromo/odfs/${odfNId}/conectores`);
}


// ── Visor en vivo de un elemento Cromo ───────────────────────────────────────
// GET directo contra Cromo (nunca contra las tablas ya ingeridas) — para auditar inconsistencias sin
// esperar a la próxima corrida de ingesta. Mismo criterio de auth que el resto: cualquier usuario
// autenticado. A diferencia de `CromoDetalleCable`/`CromoVerificacion*`, esto nunca se persiste.

export interface CromoAtributoVivo {
  id: number;
  etiqueta: string;
  valor: unknown;
}

export interface CromoElementoVivo {
  n_id: number;
  version_id: number | null;
  clase: number | null;
  clase_etiqueta: string | null;
  clase_entidad: string | null;
  nombre: string | null;
  notas: string | null;
  atributos: CromoAtributoVivo[];
  payload_raw: Record<string, unknown>;
}

export async function obtenerElementoVivoCromo(nId: number): Promise<CromoElementoVivo> {
  return requestJson(`/api/infra/cromo/elementos/${nId}/vivo`);
}

// ── "Validar datos DB Cromo" (Tool Kit) ──────────────────────────────────────
// Distinto de `obtenerElementoVivoCromo`: acá se le aplica el MISMO parseo que usa la ingesta
// (árbol completo de cables/tubos/pelos/fusiones), no sólo los atributos planos del objeto. Cero
// acceso a la base de datos local — los servicios de cada pelo viajan crudos, sin matchear.

export interface CromoCableValidacion {
  n_id: number;
  nombre: string | null;
  capacidad: string | null;
  extremo_a_n_id: number | null;
  extremo_a_nombre: string | null;
  extremo_b_n_id: number | null;
  extremo_b_nombre: string | null;
}

export interface CromoTuboValidacion {
  n_id: number;
  cable_n_id: number | null;
  orden: number | null;
  nombre_color: string | null;
}

export interface CromoPeloValidacion {
  n_id: number;
  tubo_n_id: number | null;
  cable_n_id: number | null;
  numero_pelo: string | null;
  color: string | null;
  servicio_raw: string | null;
  servicio_numero: string | null;
}

export interface CromoFusionValidacion {
  n_id: number;
  botella_n_id: number | null;
  nombre_par: string | null;
  pelo_a_n_id: number | null;
  pelo_b_n_id: number | null;
}

export interface CromoErrorParseo {
  n_id: number | null;
  clase: number | null;
  motivo: string;
}

export interface CromoValidacionDatos {
  n_id: number;
  clase: number | null;
  tipo_objeto: string;
  nombre: string | null;
  notas: string | null;
  latitud: number | null;
  longitud: number | null;
  codigo_modelo: string | null;
  id_legacy: string | null;
  cables: CromoCableValidacion[];
  tubos: CromoTuboValidacion[];
  pelos: CromoPeloValidacion[];
  fusiones: CromoFusionValidacion[];
  errores_parseo: CromoErrorParseo[];
  payload_raw: Record<string, unknown>;
}

export async function validarElementoCromo(nId: number): Promise<CromoValidacionDatos> {
  return requestJson(`/api/infra/cromo/validar/${nId}`);
}

// ── Cables detectados en Cromo (ID dual: hist[]/next_id) ─────────────────────
// Distinto de `verificarServiciosPorBotella().cables` (ese lee `app.cromo_cables` YA ingerido):
// esto consulta la botella EN VIVO contra Cromo, siguiendo `hist[]`/`next_id` si el n_id quedó
// vacío por un caso de "ID dual", para detectar cables que la ingesta omitió o vinculó a un id de
// versión viejo en vez del n_id estable. Sólo lectura, nunca persiste — el botón de escritura
// correspondiente es `repoblarCablesCromo` (api/botellas.ts, sólo admin).

export interface CromoCableDetectado {
  n_id: number;
  nombre: string | null;
  extremo_a_n_id: number | null;
  extremo_b_n_id: number | null;
  /** "OK" = ya vinculado correctamente local · "FALTA" = no existe local · "DESACTUALIZADO" =
   * existe pero con un extremo desactualizado (apunta a un id de versión viejo de la botella). */
  estado_local: 'OK' | 'FALTA' | 'DESACTUALIZADO';
}

export interface CromoCablesDetectadosResultado {
  botella_n_id: number;
  ids_cadena: number[];
  cables: CromoCableDetectado[];
}

export async function detectarCablesCromo(botellaNId: number): Promise<CromoCablesDetectadosResultado> {
  return requestJson(`/api/infra/cromo/botellas/${botellaNId}/cables-detectados`);
}

// ── Detalle jerárquico de un ODF (Tarea 5, plan ODFs) ────────────────────────
// Distinto del inventario (listar/buscar): esto es "mostrame este ODF puntual" — dirección
// completa, cables que lo tienen asociado y otros ODFs en la misma dirección física.

export interface CromoOdfCableAsociado {
  n_id: number;
  nombre: string | null;
}

export interface CromoOdfVecinoDireccion {
  n_id: number;
  nombre: string | null;
}

export interface CromoDetalleOdf {
  n_id: number;
  nombre: string | null;
  tipo_elemento: string;
  propietario: string | null;
  codigo_modelo: string | null;
  id_legacy: string | null;
  notas: string | null;
  calle: string | null;
  altura: string | null;
  localidad: string | null;
  provincia: string | null;
  ubicacion_fisica: string | null;
  tendido: string | null;
  latitud: number | null;
  longitud: number | null;
  vigente: boolean;
  cables_asociados: CromoOdfCableAsociado[];
  odfs_en_la_misma_direccion: CromoOdfVecinoDireccion[];
}

export async function obtenerDetalleOdf(nId: number): Promise<CromoDetalleOdf> {
  return requestJson(`/api/infra/cromo/odfs/${nId}/detalle`);
}
