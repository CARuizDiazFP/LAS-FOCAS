// Nombre de archivo: servicioSecciones.ts
// Ubicación de archivo: web/frontend/src/api/servicioSecciones.ts
// Descripción: Cliente y tipos de las secciones del Detalle de Servicio (camino FO, ODFs, ingresos,
// reclamos y baneos) — compartidos entre la ficha compacta y cada vista dedicada

/**
 * Estos tipos y llamadas vivían declarados INLINE dentro de `ServicioDetalleView.vue`, junto con
 * cinco `fetch` crudos y un `parseJsonOrError` duplicado. Al partir la ficha en tarjetas con una
 * vista propia por sección, cada una necesita los mismos datos: dejarlos en la vista habría
 * obligado a duplicarlos cinco veces.
 *
 * Todas las llamadas pasan por `requestJson`, que ya unifica el manejo de errores del SPA.
 */

import { requestJson } from './client';

// ── ODFs asociadas ────────────────────────────────────────────────────────

/**
 * Fuente: el archivo de tracking de la ruta, no Cromo. `empalme_id` siempre viene como string
 * (regex del parser); `camara_*` son `null` cuando no hay match en `app.empalmes`; `ruta_tipo`
 * nunca llega `null` desde el backend (default "PRINCIPAL" ya resuelto server-side).
 */
export interface InfraOdfTerminal {
  odf_id: string;
  conector: string;
}

export interface InfraOdfEmpalme {
  empalme_id: string;
  descripcion: string;
  es_transito: boolean;
  camara_id: number | null;
  camara_nombre: string | null;
  camara_estado: string | null;
}

export interface InfraOdfRuta {
  ruta_id: number;
  ruta_nombre: string;
  ruta_tipo: string;
  activa: boolean;
  sin_tracking: boolean;
  terminal_a: InfraOdfTerminal | null;
  terminal_b: InfraOdfTerminal | null;
  transitos_count: number;
  empalmes_count: number;
  empalmes: InfraOdfEmpalme[];
}

export interface InfraOdfsResponse {
  status: string;
  servicio_id: string;
  total_odfs: number;
  total_empalmes: number;
  rutas: InfraOdfRuta[];
}

export async function getOdfsServicio(idOrigen: string): Promise<InfraOdfsResponse> {
  return requestJson<InfraOdfsResponse>(
    `/api/infra/servicios/${encodeURIComponent(idOrigen)}/odfs`,
  );
}

// ── ODFs del Servicio en Cromo (canal por defecto) ────────────────────────

/**
 * Fuente: lo ya ingerido de Cromo, que es la fuente de verdad para las ODFs de un Servicio
 * (`docs/decisiones.md`, 2026-09-09). Distinto de `getOdfsServicio`, que deriva ODFs del archivo
 * de tracking manual y sólo existe para regularizar lo que Cromo no resuelve solo.
 *
 * `origen` dice por cuál vía se resolvió: `servicio_resuelto` es la definición canónica que
 * también usa el gestor de Servicios sin ODF; `pelo` es real pero ese gestor NO la ve (31 casos
 * en dev); `override_manual` es una asociación confirmada a mano por un operador.
 */
export interface CromoOdfDeServicio {
  odf_n_id: number;
  nombre: string | null;
  calle: string | null;
  altura: string | null;
  localidad: string | null;
  conectores: number;
  pelos: number;
  origen: 'servicio_resuelto' | 'pelo' | 'override_manual';
}

export interface CromoOdfsDeServicioResponse {
  servicio_id: number;
  total: number;
  odfs: CromoOdfDeServicio[];
}

/** Ojo: toma la PK interna del Servicio, no el ID de origen — igual que el resto de la familia
 * `/api/infra/cromo/servicios/...`, y al revés que `getOdfsServicio`. */
export async function getOdfsCromoServicio(
  servicioId: number,
): Promise<CromoOdfsDeServicioResponse> {
  return requestJson<CromoOdfsDeServicioResponse>(
    `/api/infra/cromo/servicios/${servicioId}/odfs`,
  );
}

// ── Ingresos técnicos ─────────────────────────────────────────────────────

/**
 * Ingresos técnicos (Slack) a las cámaras que atraviesa el servicio. `tecnico_id` guarda el nombre
 * resuelto del técnico (vía Slack `users.info`) para filas creadas desde el fix de 2026-09-04 en
 * adelante — filas anteriores a ese deploy pueden todavía tener el id crudo de Slack (p. ej.
 * "U0AUB6CRE4A") si nunca se cerraron con un Egreso posterior. `botella_label`/`tipo` distinguen la
 * Botella resuelta y un `INTENTO_BLOQUEADO` (que también tiene `fecha_fin: null`, igual que un
 * ingreso real "en curso") de un ingreso real.
 */
export interface InfraServicioIngreso {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
  botella_label: string;
  tipo: string;
  camara_id: number;
  camara_nombre: string | null;
  /** Baja lógica: sólo llegan anulados si un admin los pide (`incluirAnulados`). */
  anulado: boolean;
  anulado_at: string | null;
  anulado_por: string | null;
  anulado_motivo: string | null;
}

export interface InfraServicioIngresosResponse {
  status: string;
  servicio_id: string;
  /** Cuenta SIEMPRE sólo los vigentes, también cuando se incluyen anulados. */
  total: number;
  /** Presente sólo si se pidieron (y se devolvieron) anulados. */
  total_anulados?: number;
  ingresos: InfraServicioIngreso[];
}

/**
 * `incluirAnulados` sólo tiene efecto para un admin: a un usuario común el backend lo ignora y
 * devuelve sólo los vigentes.
 */
export async function getIngresosServicio(
  idOrigen: string,
  incluirAnulados = false,
): Promise<InfraServicioIngresosResponse> {
  const qs = incluirAnulados ? '?incluir_anulados=1' : '';
  return requestJson<InfraServicioIngresosResponse>(
    `/api/infra/servicios/${encodeURIComponent(idOrigen)}/ingresos${qs}`,
  );
}

export interface RegistrarEgresoResponse {
  ok: boolean;
  resultado: string;
  mensaje: string;
  ingreso: { id: number; fecha_inicio: string | null; fecha_fin: string | null };
}

/**
 * Cierra un ingreso que quedó "en curso" (`POST /api/infra/ingresos/{id}/egreso`). `momentoIso` debe
 * traer zona horaria (el backend rechaza fechas naive); queda auditado en `app.ingresos_correcciones`
 * con `origen='web'`, igual que el comando Slack "Forzar egreso #<id>".
 */
export async function registrarEgresoIngreso(
  ingresoId: number,
  momentoIso: string,
  motivo: string,
): Promise<RegistrarEgresoResponse> {
  return requestJson<RegistrarEgresoResponse>(`/api/infra/ingresos/${ingresoId}/egreso`, {
    method: 'POST',
    json: { momento: momentoIso, motivo },
    csrf: true,
  });
}

// ── Corrección de ingresos (admin): mover y anular ───────────────────────

/**
 * Lo mínimo que necesitan los modales de mover/anular de un ingreso. Lo arman tanto la vista de
 * Servicio (`InfraServicioIngreso` ya trae la cámara) como `ModalRegistros` (la cámara es la del
 * detalle abierto).
 */
export interface IngresoCorregible {
  id: number;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  tecnico_id: string | null;
  cromo_botella_id: number | null;
  botella_label: string;
  tipo: string;
  camara_id: number | null;
  camara_nombre: string | null;
}

/** Límites del motivo que valida el backend (tras `strip`). */
export const MOTIVO_CORRECCION_MIN = 3;
export const MOTIVO_CORRECCION_MAX = 500;

/**
 * Intervención de FO Monitor vinculada que el backend dejó como estaba:
 * `OTROS_INGRESOS_VIGENTES` (tiene otros ingresos vigentes en otra cámara) o
 * `CONSULTAS_YA_ENVIADAS` (ya consultó con el alcance anterior; sólo al mover).
 */
export interface IntervencionFomonOmitida {
  intervencion_id: number;
  motivo: string;
}

export interface CorreccionIngresoResponse {
  ok: boolean;
  resultado: 'OK_INGRESO_MOVIDO' | 'OK_INGRESO_ANULADO';
  mensaje: string;
  /** El ingreso ya corregido, serializado como en los listados, con su cámara (la de destino al mover). */
  ingreso: InfraServicioIngreso;
  /** Intervenciones abiertas que se reubicaron (mover) o se cancelaron (anular). */
  intervenciones_fomon: number[];
  intervenciones_fomon_omitidas: IntervencionFomonOmitida[];
}

/**
 * Mueve un ingreso a otra Cámara raíz (`POST /api/admin/infra/ingresos/{id}/mover`), sólo admin.
 * `cromoBotellaNId` es el `n_id` de una CromoBotella vigente del destino; `null` lo deja sin botella.
 * Los rechazos llegan como `ApiError` con el texto del backend (`{"error": ...}`): 404 ingreso o
 * cámara inexistente, 409 ingreso anulado o mismo destino, 422 motivo/botella inválidos o destino
 * que no es una cámara raíz.
 */
export async function moverIngreso(
  ingresoId: number,
  camaraDestinoId: number,
  cromoBotellaNId: number | null,
  motivo: string,
): Promise<CorreccionIngresoResponse> {
  return requestJson<CorreccionIngresoResponse>(`/api/admin/infra/ingresos/${ingresoId}/mover`, {
    method: 'POST',
    json: {
      camara_destino_id: camaraDestinoId,
      cromo_botella_destino_n_id: cromoBotellaNId,
      motivo,
    },
    csrf: true,
  });
}

/**
 * Anula un ingreso que nunca ocurrió (`POST /api/admin/infra/ingresos/{id}/anular`), sólo admin.
 * Baja lógica auditada: deja de contar para el estado de la cámara y de listarse. 409 si ya estaba
 * anulado, 422 si el motivo no tiene entre 3 y 500 caracteres.
 */
export async function anularIngreso(
  ingresoId: number,
  motivo: string,
): Promise<CorreccionIngresoResponse> {
  return requestJson<CorreccionIngresoResponse>(`/api/admin/infra/ingresos/${ingresoId}/anular`, {
    method: 'POST',
    json: { motivo },
    csrf: true,
  });
}

// ── Baneos ────────────────────────────────────────────────────────────────

/**
 * `rol` distingue si el Servicio fue el **protegido** (se baneó a otros para cuidarlo) o el
 * **afectado** (se lo baneó para cuidar a un tercero): son dos lecturas muy distintas de la misma
 * fila. El backend matchea por las tres identidades del Servicio, porque `app.incidentes_baneo`
 * guarda los extremos como texto y no como FK.
 */
export interface ServicioBaneo {
  id: number;
  ticket_asociado: string | null;
  servicio_afectado_id: string;
  servicio_protegido_id: string;
  usuario_ejecutor: string | null;
  motivo: string | null;
  fecha_inicio: string | null;
  fecha_fin: string | null;
  activo: boolean;
  rol: 'PROTEGIDO' | 'AFECTADO' | string;
}

export interface ServicioBaneosResponse {
  servicio_id: number;
  total: number;
  activos: number;
  eventos: ServicioBaneo[];
}

export async function getBaneosServicio(servicioId: number): Promise<ServicioBaneosResponse> {
  return requestJson<ServicioBaneosResponse>(`/api/servicios/${servicioId}/baneos`);
}
