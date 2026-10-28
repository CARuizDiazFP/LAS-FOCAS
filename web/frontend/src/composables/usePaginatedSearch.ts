// Nombre de archivo: usePaginatedSearch.ts
// Ubicación de archivo: web/frontend/src/composables/usePaginatedSearch.ts
// Descripción: Paginación incremental de los viewers (offset/limit, merge sin duplicados, recarga desde cero con debounce) con contador de generación que descarta respuestas de consultas viejas

import { onBeforeUnmount, ref, type Ref } from 'vue';

/** Forma mínima de una página: los viewers cuyo endpoint devuelve otra clave (`botellas`,
 * `camaras`, `servicios`) la mapean a `items` dentro de `cargarPagina`. */
export interface PaginaViewer<T> {
  items: T[];
  total: number;
}

export interface OpcionesPaginatedSearch<T, R extends PaginaViewer<T>> {
  limit: number;
  /** Trae una página con los filtros vigentes del viewer. */
  cargarPagina: (offset: number, limit: number) => Promise<R>;
  /** Clave para no duplicar un item que ya está en la lista al mergear la página siguiente. */
  claveItem: (item: T) => string | number;
  /** Datos extra de la respuesta (p. ej. conteos de chips). Se llama antes de mergear los items. */
  alRecibir?: (respuesta: R) => void;
  /** Estado propio del viewer que se reinicia con la lista (p. ej. la selección de filas). Corre al
   * principio de cada `recargarDesdeCero`, también la disparada por `recargarConDebounce`. */
  alReiniciar?: () => void;
  /** Mensaje si el error no es un `Error` con mensaje propio. */
  mensajeError: string;
  /** Espera de `recargarConDebounce`; default 320 ms. */
  debounceMs?: number;
}

export interface PaginatedSearch<T> {
  items: Ref<T[]>;
  total: Ref<number>;
  loading: Ref<boolean>;
  error: Ref<string>;
  hasMore: Ref<boolean>;
  cargarSiguiente: () => Promise<void>;
  recargarDesdeCero: () => Promise<void>;
  recargarConDebounce: () => void;
}

export function usePaginatedSearch<T, R extends PaginaViewer<T>>(
  o: OpcionesPaginatedSearch<T, R>,
): PaginatedSearch<T> {
  const items = ref([]) as Ref<T[]>;
  const total = ref(0);
  const loading = ref(false);
  const error = ref('');
  const hasMore = ref(true);

  let offset = 0;
  let generacion = 0;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  // Push en el mismo array (no reasigna): un `watch(items)` no profundo del viewer sigue
  // disparando sólo al reiniciar la lista, igual que antes.
  function mergeItems(next: T[]): void {
    const vistos = new Set(items.value.map((item) => o.claveItem(item)));
    for (const item of next) {
      const clave = o.claveItem(item);
      if (vistos.has(clave)) continue;
      vistos.add(clave);
      items.value.push(item);
    }
  }

  async function cargarSiguiente(): Promise<void> {
    if (loading.value || !hasMore.value) return;
    const propia = generacion;
    loading.value = true;
    error.value = '';
    try {
      const respuesta = await o.cargarPagina(offset, o.limit);
      if (propia !== generacion) return;
      total.value = respuesta.total;
      o.alRecibir?.(respuesta);
      mergeItems(respuesta.items);
      offset += respuesta.items.length;
      hasMore.value = respuesta.items.length === o.limit && offset < respuesta.total;
    } catch (err: unknown) {
      if (propia !== generacion) return;
      error.value = err instanceof Error ? err.message : o.mensajeError;
    } finally {
      if (propia === generacion) loading.value = false;
    }
  }

  // Generación: cada recarga invalida la consulta en vuelo. Su respuesta (o su error) llega igual,
  // pero se descarta entera: no mergea, no toca total/hasMore/error ni apaga el `loading` de la
  // consulta nueva. Por eso la recarga baja `loading` antes de pedir: si no, el guard de
  // `cargarSiguiente` la ignoraría mientras la consulta vieja sigue en vuelo (antes pasaba al tipear
  // durante una carga: la búsqueda nueva no salía y la respuesta vieja se mezclaba en la lista vacía).
  async function recargarDesdeCero(): Promise<void> {
    generacion += 1;
    o.alReiniciar?.();
    items.value = [];
    total.value = 0;
    offset = 0;
    hasMore.value = true;
    loading.value = false;
    await cargarSiguiente();
  }

  function recargarConDebounce(): void {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      void recargarDesdeCero();
    }, o.debounceMs ?? 320);
  }

  onBeforeUnmount(() => {
    if (debounceTimer) clearTimeout(debounceTimer);
  });

  return { items, total, loading, error, hasMore, cargarSiguiente, recargarDesdeCero, recargarConDebounce };
}
