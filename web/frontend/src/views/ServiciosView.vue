<!--
  Nombre de archivo: ServiciosView.vue
  Ubicación de archivo: web/frontend/src/views/ServiciosView.vue
  Descripción: Visor de servicios con búsqueda multipropósito y scroll infinito
-->
<template>
  <section class="servicios-view">
    <header class="servicios-view__header">
      <h1>Servicios</h1>
      <p>Buscador multipropósito con paginación incremental para operación diaria.</p>
    </header>

    <div class="servicios-view__toolbar">
      <input
        v-model="query"
        class="servicios-view__search"
        type="search"
        placeholder="Buscar por ID, cliente, domicilio, tipo o estado"
        @input="onSearchInput"
      />
      <button class="btn primary" type="button" :disabled="loading" @click="reloadFromZero">
        {{ loading && items.length === 0 ? 'Buscando...' : 'Actualizar' }}
      </button>
    </div>

    <p v-if="error" class="servicios-view__error">{{ error }}</p>

    <div v-if="items.length > 0" class="servicios-view__grid">
      <ServicioCard
        v-for="item in items"
        :key="item.numero_primer_servicio"
        :servicio="item"
        @open-detail="openServicioDetail"
      />
    </div>

    <div v-else-if="!loading" class="servicios-view__empty">
      No se encontraron servicios para los filtros actuales.
    </div>

    <div v-if="loading && items.length > 0" class="servicios-view__loading-more">
      Cargando más servicios...
    </div>

    <div ref="sentinel" class="servicios-view__sentinel" aria-hidden="true"></div>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import { searchServicios, type ServicioItem } from '../api/servicios';
import ServicioCard from '../components/servicios/ServicioCard.vue';

const LIMIT = 30;
const router = useRouter();

const query = ref('');
const items = ref<ServicioItem[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref('');
const offset = ref(0);
const hasMore = ref(true);
const sentinel = ref<HTMLElement | null>(null);

let observer: IntersectionObserver | null = null;
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

function mergeItems(next: ServicioItem[]): void {
  const seen = new Set(items.value.map((item) => item.numero_primer_servicio));
  for (const item of next) {
    if (seen.has(item.numero_primer_servicio)) continue;
    seen.add(item.numero_primer_servicio);
    items.value.push(item);
  }
}

async function loadNextPage(): Promise<void> {
  if (loading.value || !hasMore.value) return;

  loading.value = true;
  error.value = '';
  try {
    const response = await searchServicios({
      q: query.value.trim(),
      limit: LIMIT,
      offset: offset.value,
    });

    total.value = response.total;
    mergeItems(response.servicios);
    offset.value += response.servicios.length;
    hasMore.value = response.servicios.length === LIMIT && offset.value < response.total;
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo consultar servicios';
  } finally {
    loading.value = false;
  }
}

async function reloadFromZero(): Promise<void> {
  items.value = [];
  total.value = 0;
  offset.value = 0;
  hasMore.value = true;
  await loadNextPage();
}

function onSearchInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    void reloadFromZero();
  }, 320);
}

function openServicioDetail(idOrigen: string): void {
  const id = idOrigen.trim();
  if (!id) return;
  void router.push(`/servicios/ID/${encodeURIComponent(id)}`);
}

onMounted(async () => {
  await reloadFromZero();

  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          void loadNextPage();
        }
      }
    },
    {
      root: null,
      rootMargin: '300px 0px',
      threshold: 0.1,
    },
  );

  if (sentinel.value) observer.observe(sentinel.value);
});

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
  if (observer) observer.disconnect();
});
</script>

<style scoped>
.servicios-view {
  display: grid;
  gap: var(--space-4);
}

.servicios-view__header h1 {
  margin: 0;
  font-size: 1.4rem;
}

.servicios-view__header p {
  margin: var(--space-1) 0 0;
  color: var(--color-text-muted);
}

.servicios-view__toolbar {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-2);
}

.servicios-view__search {
  width: 100%;
  min-height: 42px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border-default);
  padding: 0 var(--space-3);
  background: var(--color-bg-surface);
  color: var(--color-text-primary);
}

.servicios-view__search:focus-visible {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: var(--shadow-focus);
}

.servicios-view__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-3);
}

.servicios-view__empty,
.servicios-view__loading-more {
  border: 1px dashed var(--color-border-default);
  border-radius: var(--radius-md);
  padding: var(--space-3);
  color: var(--color-text-muted);
  text-align: center;
  background: rgba(18, 28, 42, 0.45);
}

.servicios-view__error {
  margin: 0;
  color: #fca5a5;
}

.servicios-view__sentinel {
  height: 2px;
}

@media (max-width: 700px) {
  .servicios-view__toolbar {
    grid-template-columns: 1fr;
  }
}
</style>
