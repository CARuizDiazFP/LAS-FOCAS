// Nombre de archivo: useInfraBusqueda.ts
// Ubicación de archivo: web/frontend/src/composables/infra/useInfraBusqueda.ts
// Descripción: Búsqueda de cámaras de InfraTab: términos, smart-search paginado, filtro por estado, leyenda y no operativas

import { ref, computed } from 'vue';
import { smartSearch } from '../../api/infra';
import type { Notificar } from './tipos';

// DETECTADA y el pseudo-estado "TRACKING" (client-side, basado en camara.rutas.length > 0) fueron
// retirados del sistema (2026-08-11) — el estado operable de Cámara/Botella se redujo a
// LIBRE/OCUPADA/BANEADA/NO_OPERATIVA (ver scripts/retirar_estado_detectada.py).
const legendItems = [
  { estado: 'LIBRE', dotClass: 'libre' },
  { estado: 'OCUPADA', dotClass: 'ocupada' },
  { estado: 'BANEADA', dotClass: 'baneada' },
  { estado: 'NO_OPERATIVA', dotClass: 'no_operativa' },
];

// --- Paginación del lado del servidor (2026-08-13) — antes /infra no cargaba nada hasta que el
// usuario escribía un término o tocaba un chip de estado; ahora carga sin filtros al montar,
// paginado en `offset`/`limit`, igual contrato que ya soporta POST /api/infra/smart-search.
const PAGE_SIZE = 100;

function estadoDotClass(estado: unknown): string {
  const value = String(estado ?? 'libre').toLowerCase();
  return ['libre', 'ocupada', 'baneada', 'no_operativa'].includes(value) ? value : 'libre';
}

function camaraMeta(camara: Record<string, unknown>): string {
  const servicios = ((camara.servicios as unknown[]) ?? []).length;
  const botellas = Number(camara.botellas_count ?? 0);
  const partes: string[] = [];
  if (botellas > 0) partes.push(`${botellas} botella${botellas !== 1 ? 's' : ''}`);
  partes.push(servicios > 0 ? `${servicios} servicio${servicios !== 1 ? 's' : ''}` : 'Sin relevar');
  return partes.join(' · ');
}

function camaraIdLabel(camara: Record<string, unknown>): string {
  // Etapa Cámara/Botella: fallback al ID interno — el ID de Cromo/Fontine aún no está garantizado
  // para todas las cámaras (hoy 0% poblado en dev, ver docs/infra.md).
  const fontineId = camara.fontine_id;
  if (typeof fontineId === 'string' && fontineId.trim()) return fontineId;
  return `ID ${camara.id}`;
}

export function useInfraBusqueda(notificar: Notificar) {
  const searchInput = ref('');
  const searchTerms = ref<string[]>([]);
  const camaras = ref<Record<string, unknown>[]>([]);
  const loading = ref(false);
  const hasSearched = ref(false);
  const statusText = ref('');
  const statusVariant = ref('muted');

  const offset = ref(0);
  const total = ref(0);

  // --- Filtro rápido por estado ---
  const activeStateFilter = ref<string | null>(null);

  // --- Toggle "Mostrar No operativas" — ortogonal al chip de estado, oculto por defecto (hay que
  // activarlo para verlas), se combina con cualquier chip activo en vez de competir con ellos.
  const incluirNoOperativas = ref(false);

  function setStatus(text: string, variant = 'muted') {
    statusText.value = text;
    statusVariant.value = variant;
  }

  function addTerm() {
    const val = searchInput.value.trim();
    if (!val) return;
    if (searchTerms.value.some(t => t.toLowerCase() === val.toLowerCase())) {
      notificar('warning', 'Término duplicado', 'Este término ya está activo');
      return;
    }
    searchTerms.value.push(val);
    searchInput.value = '';
  }

  function removeTerm(i: number) {
    searchTerms.value.splice(i, 1);
  }

  function clearAll() {
    searchTerms.value = [];
    searchInput.value = '';
    activeStateFilter.value = null;
    incluirNoOperativas.value = false;
    void runSearch();
  }

  function onToggleIncluirNoOperativas() {
    void runSearch();
  }

  function toggleStateFilter(estado: string) {
    activeStateFilter.value = activeStateFilter.value === estado ? null : estado;
    void runSearch();
  }

  const legendCounts = computed<Record<string, number>>(() => {
    const counts: Record<string, number> = { LIBRE: 0, OCUPADA: 0, BANEADA: 0, NO_OPERATIVA: 0 };
    for (const camara of camaras.value) {
      const estado = String(camara.estado ?? 'LIBRE').toUpperCase();
      if (estado in counts) counts[estado] += 1;
    }
    return counts;
  });

  async function searchCamaras() {
    loading.value = true;
    hasSearched.value = true;
    const statusMsg = searchTerms.value.length > 0
      ? `Buscando con ${searchTerms.value.length} término(s)...`
      : activeStateFilter.value
        ? `Cargando cámaras ${activeStateFilter.value}...`
        : 'Cargando cámaras...';
    setStatus(statusMsg, 'loading');
    try {
      const data = await smartSearch({
        terms: searchTerms.value,
        limit: PAGE_SIZE,
        offset: offset.value,
        incluir_no_operativas: incluirNoOperativas.value,
        ...(activeStateFilter.value ? { estado: activeStateFilter.value } : {}),
      });
      camaras.value = data.camaras ?? [];
      total.value = data.total ?? camaras.value.length;
      const count = camaras.value.length;
      setStatus(
        count === 0
          ? 'Sin resultados'
          : `Mostrando ${offset.value + 1}–${offset.value + count} de ${total.value} cámaras`,
        count > 0 ? 'success' : 'muted',
      );
    } catch (e: unknown) {
      camaras.value = [];
      total.value = 0;
      setStatus(`Error: ${e instanceof Error ? e.message : String(e)}`, 'error');
    } finally {
      loading.value = false;
    }
  }

  // Cualquier cambio de términos/filtro es una consulta NUEVA — vuelve a la página 1.
  function runSearch(): Promise<void> {
    offset.value = 0;
    return searchCamaras();
  }

  function goToPage(newOffset: number): void {
    if (newOffset < 0 || newOffset >= total.value || loading.value) return;
    offset.value = newOffset;
    void searchCamaras();
  }

  function nextPage(): void {
    goToPage(offset.value + PAGE_SIZE);
  }

  function prevPage(): void {
    goToPage(offset.value - PAGE_SIZE);
  }

  // Tras una acción que cambia estados (baneo, tracking, limpieza): re-ejecuta la búsqueda
  // vigente, en la misma página, sólo si ya hubo una.
  async function refrescarSiBuscado(): Promise<void> {
    if (hasSearched.value) await searchCamaras();
  }

  return {
    PAGE_SIZE,
    searchInput,
    searchTerms,
    camaras,
    loading,
    hasSearched,
    statusText,
    statusVariant,
    offset,
    total,
    activeStateFilter,
    incluirNoOperativas,
    legendItems,
    legendCounts,
    addTerm,
    removeTerm,
    clearAll,
    onToggleIncluirNoOperativas,
    toggleStateFilter,
    estadoDotClass,
    camaraMeta,
    camaraIdLabel,
    runSearch,
    nextPage,
    prevPage,
    refrescarSiBuscado,
  };
}
