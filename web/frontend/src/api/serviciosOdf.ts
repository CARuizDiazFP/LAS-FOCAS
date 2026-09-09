// Nombre de archivo: serviciosOdf.ts
// Ubicación de archivo: web/frontend/src/api/serviciosOdf.ts
// Descripción: Cliente frontend del gestor de Servicios Activos sin ODF resuelta — listado paginado, sugerencia de ODF y confirmación manual de asociación

import { requestJson } from './client';

// ── Vocabulario ───────────────────────────────────────────────────────────
// Mismos literales que `core/services/cromo/servicios_sin_odf.py` (CATEGORIAS_POR_PRIORIDAD) y el
// CHECK de `app.cromo_servicio_odf_override` — no se reimplementa la taxonomía acá, sólo se calca.

export const CATEGORIAS_SERVICIO_SIN_ODF = [
  'OLT_PON_COMPARTIDO',
  'EQUIPO_DOMICILIO_CLIENTE',
  'SWITCH_COMPARTIDO_REVISAR',
  'SIN_SENAL_PROV',
] as const;

export type CategoriaServicioSinOdf = (typeof CATEGORIAS_SERVICIO_SIN_ODF)[number];

const CATEGORIA_LABELS: Record<CategoriaServicioSinOdf, string> = {
  OLT_PON_COMPARTIDO: 'OLT / PON compartido',
  EQUIPO_DOMICILIO_CLIENTE: 'Equipo en domicilio del cliente',
  SWITCH_COMPARTIDO_REVISAR: 'Switch compartido — revisar',
  SIN_SENAL_PROV: 'Sin señal PROV',
};

export function categoriaServicioLabel(categoria: string): string {
  return CATEGORIA_LABELS[categoria as CategoriaServicioSinOdf] ?? categoria;
}

/** Token de color semántico por categoría (mismo sistema `--color-state-*` que los chips de
 * Cámaras/Botellas). Elegido por cuánto puede *hacer* el operador con la fila, no por gravedad:
 * `OLT_PON_COMPARTIDO` es la única categoría con sugerencia automática de ODF (ok/verde),
 * `SWITCH_COMPARTIDO_REVISAR` requiere criterio manual (warn/ámbar), `SIN_SENAL_PROV` no tiene
 * ningún dato PROV para trabajar (error/rojo), y `EQUIPO_DOMICILIO_CLIENTE` es un diagnóstico
 * limpio sin acción sugerida todavía (idle/gris). */
export type CategoriaServicioToken = 'ok' | 'warn' | 'error' | 'idle';

const CATEGORIA_TOKENS: Record<CategoriaServicioSinOdf, CategoriaServicioToken> = {
  OLT_PON_COMPARTIDO: 'ok',
  EQUIPO_DOMICILIO_CLIENTE: 'idle',
  SWITCH_COMPARTIDO_REVISAR: 'warn',
  SIN_SENAL_PROV: 'error',
};

export function categoriaServicioToken(categoria: string): CategoriaServicioToken {
  return CATEGORIA_TOKENS[categoria as CategoriaServicioSinOdf] ?? 'idle';
}

const SUBCATEGORIA_LABELS: Record<string, string> = {
  PELO_SIN_CONECTOR_ODF: 'Cromo tiene el pelo, pero no está cableado a un conector de ODF',
  AUSENTE_RED_CROMO: 'Cromo no conoce este Servicio (sin pelo matcheado)',
  BAJA_LOGICA_HEREDADA: 'La fibra quedó asociada a un Servicio hermano dado de Baja',
};

export function subcategoriaLabel(subcategoria: string | null): string | null {
  if (!subcategoria) return null;
  return SUBCATEGORIA_LABELS[subcategoria] ?? subcategoria;
}

export type SenalDireccion = 'coincide' | 'no_coincide' | 'no_se_pudo_comparar';

// ── Listado paginado ─────────────────────────────────────────────────────

export interface ExtremoUltimaMilla {
  extremo: number | null;
  nodo: string | null;
  equipo: string | null;
}

export interface ServicioSinOdfItem {
  id: number;
  servicio_id: string;
  numero_primer_servicio: string | null;
  nombre_cliente: string | null;
  categoria_causa: string;
  subcategoria: string | null;
  nodo: string | null;
  equipo: string | null;
  extremos: ExtremoUltimaMilla[];
  indice_extremo_categorizado: number | null;
}

export interface ListadoServiciosSinOdfResponse {
  total: number;
  limit: number;
  offset: number;
  items: ServicioSinOdfItem[];
  /** Las 4 categorías con su conteo real, sobre el mismo conjunto filtrado por `q` y ANTES del
   * filtro `categoria` (los chips siguen mostrando el número de las otras categorías mientras una
   * está seleccionada). Viene con el listado a propósito: el backend ya categorizó todas las filas
   * candidatas en esa misma pasada, así que pedirlo por separado costaba 4 ejecuciones extra de la
   * query más cara de la feature para devolver 4 enteros. */
  conteos_por_categoria: Record<string, number>;
}

export interface ListarServiciosSinOdfParams {
  categoria?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

function toQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    query.set(key, String(value));
  });
  const qs = query.toString();
  return qs ? `?${qs}` : '';
}

/** Página del universo "Servicios Activos verificables sin ODF resuelta", ya categorizada por
 * fila, más `conteos_por_categoria` para los chips (ver
 * `core/services/cromo/servicios_sin_odf.py::listar_servicios_sin_odf`). `limit: 0` sigue siendo
 * válido y devuelve `items: []` con el `total` real, pero ya NO hace falta para los conteos. */
export async function listarServiciosSinOdf(
  params: ListarServiciosSinOdfParams,
): Promise<ListadoServiciosSinOdfResponse> {
  return requestJson<ListadoServiciosSinOdfResponse>(
    `/api/admin/infra/servicios-odf/listado${toQuery({
      categoria: params.categoria,
      q: params.q,
      limit: params.limit,
      offset: params.offset,
    })}`,
  );
}

// ── Sugerencia de ODF para un Servicio puntual ───────────────────────────

export interface SugerenciaOdf {
  odf_n_id: number;
  nombre: string | null;
  /** Cuántas ODFs candidatas había para este Servicio (siempre `>= 1`; se devuelve UNA sola, la
   * más corroborada). La UI TIENE que avisar cuando es `> 1`: mostrar una sola ODF sin decir que
   * había 4 le esconde al operador que estaba eligiendo entre opciones — 88 de 1057 Servicios
   * `OLT_PON_COMPARTIDO` con sugerencia tienen más de una candidata (medido real 2026-09-09). */
  cantidad_candidatas: number;
}

export interface SugerenciaServicioResponse {
  id: number;
  servicio_id: string;
  nombre_cliente: string | null;
  direccion: string | null;
  categoria_causa: string;
  subcategoria: string | null;
  extremos: ExtremoUltimaMilla[];
  indice_extremo_categorizado: number | null;
  sugerencia: SugerenciaOdf | null;
  senal_direccion: SenalDireccion | null;
}

/** Detalle + sugerencia de ODF de UN Servicio sin ODF. Cualquier usuario autenticado puede
 * consultarlo (no requiere admin) — es sólo lectura, nada se aplica acá. */
export async function getSugerenciaServicio(servicioId: number): Promise<SugerenciaServicioResponse> {
  return requestJson<SugerenciaServicioResponse>(`/api/admin/infra/servicios-odf/${servicioId}/sugerencia`);
}

// ── Preview de señal de dirección (fix round 1) ──────────────────────────

export interface SenalDireccionPreviewResponse {
  senal_direccion: SenalDireccion;
}

/** Preview de `senal_direccion` para una ODF que el operador eligió A MANO en el buscador —
 * `GET .../sugerencia` sólo la calcula contra la ODF que la propia API sugirió, y esa sugerencia
 * sólo existe para la categoría `OLT_PON_COMPARTIDO` (47% de los Servicios sin ODF no la tienen).
 * Puro read-only: nunca persiste nada, `POST .../asociar` sigue siendo quien recalcula y persiste
 * la señal real contra la ODF que termine eligiéndose. Cualquier usuario autenticado puede
 * consultarlo (no requiere admin), mismo criterio que `getSugerenciaServicio`. */
export async function getSenalDireccionPreview(
  servicioId: number,
  odfNId: number,
): Promise<SenalDireccionPreviewResponse> {
  return requestJson<SenalDireccionPreviewResponse>(
    `/api/admin/infra/servicios-odf/${servicioId}/senal-direccion?odf_n_id=${odfNId}`,
  );
}

// ── Confirmación manual de asociación ────────────────────────────────────

export interface AsociarServicioOdfBody {
  odfNId: number;
  peloNId?: number | null;
  notas?: string | null;
}

export interface AsociarServicioOdfResponse {
  ok: boolean;
  categoria_causa: string;
  senal_direccion: SenalDireccion;
}

/** Confirma la asociación Servicio→ODF que eligió el operador. El backend recalcula
 * `senal_direccion` contra la ODF realmente elegida (nunca confía en lo que mandó el frontend) y
 * la persiste — nunca bloquea por un `no_coincide`, sólo lo informa. Admin + CSRF. */
export async function asociarServicioOdf(
  servicioId: number,
  body: AsociarServicioOdfBody,
): Promise<AsociarServicioOdfResponse> {
  return requestJson<AsociarServicioOdfResponse>(`/api/admin/infra/servicios-odf/${servicioId}/asociar`, {
    method: 'POST',
    json: {
      odf_n_id: body.odfNId,
      pelo_n_id: body.peloNId ?? null,
      notas: body.notas ?? null,
    },
    csrf: true,
  });
}
