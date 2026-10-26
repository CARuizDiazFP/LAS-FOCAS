// Nombre de archivo: clientesCategoria.ts
// Ubicación de archivo: web/frontend/src/admin/api/clientesCategoria.ts
// Descripción: Cliente del panel admin "Clientes por categoría" — listado, cambio, lista oficial, alias, fusión y sync

import { ApiError, CSRF_HEADER, getCsrfToken, requestJson } from '../../api/client';

// ─── Tipos ───────────────────────────────────────────────────────────────

export type OrigenCategoriaCliente = 'LISTA' | 'MANUAL' | 'SLA' | 'AUTO';
export type ModoLista = 'agregar' | 'reemplazar';
/** Claves de grupo que devuelve el backend: "6".."0" y "sin" (= sin categorizar). */
export type ClaveGrupoCliente = '6' | '5' | '4' | '3' | '2' | '1' | '0' | 'sin';

export const ORDEN_GRUPOS_CLIENTES: ClaveGrupoCliente[] = ['6', '5', '4', '3', '2', '1', '0', 'sin'];

export interface ClienteAlias {
  id: number;
  nombre_original: string;
  origen: string;
  /** El alias cuya clave es la del cliente: el backend no permite quitarlo. */
  canonico: boolean;
}

export interface ClienteCategoria {
  id: number;
  nombre: string;
  categoria: number | null;
  origen_categoria: OrigenCategoriaCliente;
  a_revisar: boolean;
  servicios: number;
  excepciones: number;
  alias: ClienteAlias[];
}

export interface ClientesPorCategoriaResponse {
  grupos: Record<ClaveGrupoCliente, ClienteCategoria[]>;
}

export interface ResumenSync {
  clientes_creados: number;
  clientes_recalculados: number;
  servicios_actualizados: number;
}

export interface CambiarCategoriaResponse {
  actualizados: number;
  no_encontrados: number[];
  sync: ResumenSync;
}

export interface ItemListaCoincidente {
  cliente_id: number;
  nombre: string;
  nombre_lista: string;
  categoria_actual: number | null;
  origen_actual: OrigenCategoriaCliente;
}

export interface ItemListaQuitado {
  cliente_id: number;
  nombre: string;
  categoria_actual: number | null;
}

export interface SugerenciaCliente {
  id: number;
  nombre: string;
}

export interface PrevisualizacionLista {
  categoria: number | null;
  modo: ModoLista;
  sube: ItemListaCoincidente[];
  baja: ItemListaCoincidente[];
  sin_cambio: ItemListaCoincidente[];
  nuevos: string[];
  /** `{nombre de la lista sin match: clientes parecidos}`. */
  sugerencias: Record<string, SugerenciaCliente[]>;
  quitados: ItemListaQuitado[];
}

export interface AplicarListaResponse extends PrevisualizacionLista {
  creados: number;
  sync: ResumenSync;
}

export interface FusionarResponse {
  destino_id: number;
  fusionados: number[];
  alias_movidos: number;
  sync: ResumenSync;
}

/** Origen de la lista: nombres pegados en el textarea o un archivo (.xlsx/.xlsm/.csv/.txt). */
export type FuenteLista = { tipo: 'nombres'; nombres: string[] } | { tipo: 'archivo'; archivo: File };

export const EXTENSIONES_LISTA = '.xlsx,.xlsm,.csv,.txt';
export const TAMANO_MAXIMO_LISTA = 5 * 1024 * 1024;

// ─── Endpoints ───────────────────────────────────────────────────────────

const BASE = '/api/admin/clientes';

export async function getClientesPorCategoria(): Promise<ClientesPorCategoriaResponse> {
  return requestJson<ClientesPorCategoriaResponse>(`${BASE}/por-categoria`);
}

/** Fija la categoría (`null` = sin categorizar) de los clientes, o los vuelve a automático. */
export async function cambiarCategoriaClientes(
  clienteIds: number[],
  cambio: { categoria: number | null } | { automatico: true },
): Promise<CambiarCategoriaResponse> {
  const json =
    'automatico' in cambio
      ? { cliente_ids: clienteIds, categoria: null, automatico: true }
      : { cliente_ids: clienteIds, categoria: cambio.categoria, automatico: false };
  return requestJson<CambiarCategoriaResponse>(`${BASE}/categoria`, { method: 'PATCH', json, csrf: true });
}

/** Sube la lista por XHR (multipart). Mismo patrón que `ingestServiciosFile` en `api/servicios.ts`. */
function subirListaArchivo<T>(url: string, archivo: File, categoria: number | null, modo: ModoLista): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url, true);
    xhr.withCredentials = true;
    xhr.setRequestHeader(CSRF_HEADER, getCsrfToken());

    xhr.onload = () => {
      let payload: unknown = null;
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        payload = null;
      }

      if (xhr.status >= 200 && xhr.status < 300 && payload && typeof payload === 'object') {
        resolve(payload as T);
        return;
      }

      let message = `Error ${xhr.status}`;
      if (payload && typeof payload === 'object') {
        const candidato = payload as { error?: unknown; detail?: unknown };
        for (const valor of [candidato.error, candidato.detail]) {
          if (typeof valor === 'string' && valor.trim()) {
            message = valor;
            break;
          }
        }
      }
      reject(new ApiError(message, xhr.status || 500, payload));
    };

    xhr.onerror = () => {
      reject(new ApiError('No se pudo completar la subida del archivo', 0));
    };

    const data = new FormData();
    data.append('file', archivo, archivo.name);
    // El backend exige `categoria` siempre; "sin" = sin categorizar.
    data.append('categoria', categoria === null ? 'sin' : String(categoria));
    data.append('modo', modo);
    data.append('csrf_token', getCsrfToken());
    xhr.send(data);
  });
}

function enviarLista<T>(operacion: 'previsualizar' | 'aplicar', fuente: FuenteLista, categoria: number | null, modo: ModoLista): Promise<T> {
  const url = `${BASE}/lista/${operacion}`;
  if (fuente.tipo === 'archivo') {
    return subirListaArchivo<T>(url, fuente.archivo, categoria, modo);
  }
  return requestJson<T>(url, { method: 'POST', json: { nombres: fuente.nombres, categoria, modo }, csrf: true });
}

export function previsualizarLista(fuente: FuenteLista, categoria: number | null, modo: ModoLista): Promise<PrevisualizacionLista> {
  return enviarLista<PrevisualizacionLista>('previsualizar', fuente, categoria, modo);
}

export function aplicarLista(fuente: FuenteLista, categoria: number | null, modo: ModoLista): Promise<AplicarListaResponse> {
  return enviarLista<AplicarListaResponse>('aplicar', fuente, categoria, modo);
}

export async function fusionarClientes(destinoId: number, origenIds: number[]): Promise<FusionarResponse> {
  return requestJson<FusionarResponse>(`${BASE}/fusionar`, {
    method: 'POST',
    json: { destino_id: destinoId, origen_ids: origenIds },
    csrf: true,
  });
}

export async function agregarAliasCliente(clienteId: number, nombre: string): Promise<ClienteAlias> {
  return requestJson<ClienteAlias>(`${BASE}/${clienteId}/alias`, { method: 'POST', json: { nombre }, csrf: true });
}

export async function quitarAliasCliente(aliasId: number): Promise<void> {
  await requestJson<unknown>(`${BASE}/alias/${aliasId}`, { method: 'DELETE', json: {}, csrf: true });
}

export async function sincronizarClientes(): Promise<ResumenSync> {
  return requestJson<ResumenSync>(`${BASE}/sincronizar`, { method: 'POST', json: {}, csrf: true });
}

// ─── Presentación ────────────────────────────────────────────────────────

export function etiquetaGrupo(clave: ClaveGrupoCliente): string {
  return clave === 'sin' ? 'Sin categorizar' : `C${clave}`;
}

export function etiquetaOrigen(origen: OrigenCategoriaCliente): string {
  return { LISTA: 'Lista', MANUAL: 'Manual', SLA: 'SLA', AUTO: 'Auto' }[origen] ?? origen;
}
