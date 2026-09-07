<!--
  Nombre de archivo: ModalAsociarHuerfanas.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalAsociarHuerfanas.vue
  Descripción: Modal para asociar una o más Botellas Cromo huérfanas a una Cámara existente o nueva — resolución individual o masiva
-->
<template>
  <dialog ref="dialogEl" class="asociar-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="asociar-title-row">
        <strong>Asociar {{ descripcion }}</strong>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <div class="asociar-tabs" role="tablist">
        <button
          type="button"
          :class="['asociar-tab', { active: modo === 'existente' }]"
          @click="modo = 'existente'"
        >Cámara existente</button>
        <button
          type="button"
          :class="['asociar-tab', { active: modo === 'nueva' }]"
          @click="modo = 'nueva'"
        >Cámara nueva</button>
      </div>

      <template v-if="modo === 'existente'">
        <input
          v-if="!seleccionada"
          v-model="query"
          type="text"
          placeholder="Buscar Cámara por nombre..."
          class="asociar-search"
          @input="onSearchInput"
        />

        <div v-if="!seleccionada">
          <div v-if="buscando" class="asociar-empty">Buscando...</div>
          <div v-else-if="query.trim() && resultados.length === 0" class="asociar-empty">
            Ninguna Cámara coincide con "{{ query }}".
          </div>
          <ul v-else-if="resultados.length" class="asociar-results">
            <li
              v-for="candidata in resultados"
              :key="candidata.id"
              class="asociar-result-item"
              @click="seleccionada = candidata"
            >
              <strong>{{ candidata.nombre }}</strong>
              <span class="asociar-result-meta">ID {{ candidata.id }} · {{ candidata.estado }}</span>
            </li>
          </ul>
        </div>
        <div v-else class="asociar-seleccion">
          <span>Cámara elegida: <strong>{{ seleccionada.nombre }}</strong></span>
          <button class="btn subtle" type="button" @click="seleccionada = null">Cambiar</button>
        </div>
      </template>

      <template v-else>
        <input
          v-model="nombreNueva"
          type="text"
          placeholder="Nombre de la Cámara nueva (ej. dirección real del sitio)"
          class="asociar-search"
        />
        <p class="asociar-hint">
          Nace en estado <strong>NO_OPERATIVA</strong> — sin señal operativa real todavía.
        </p>
      </template>

      <div v-if="error" class="asociar-empty error">{{ error }}</div>

      <div class="asociar-actions">
        <button
          class="btn primary"
          type="button"
          :disabled="confirmando || !puedeConfirmar"
          @click="handleConfirmar"
        >
          {{ confirmando ? 'Asociando...' : 'Confirmar asociación' }}
        </button>
        <button class="btn subtle" type="button" :disabled="confirmando" @click="handleClose">Cancelar</button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useSession } from '../../composables/useSession';

interface CamaraCandidata {
  id: number;
  nombre: string;
  direccion: string | null;
  estado: string;
  botellas_count: number;
}

const props = defineProps<{
  open: boolean;
  nIds: number[];
}>();

const emit = defineEmits<{
  close: [];
  asociada: [payload: { camaraId: number; camaraCreada: boolean; botellasVinculadas: number }];
}>();

const { csrf } = useSession();
const dialogEl = ref<HTMLDialogElement | null>(null);
const modo = ref<'existente' | 'nueva'>('existente');
const query = ref('');
const resultados = ref<CamaraCandidata[]>([]);
const seleccionada = ref<CamaraCandidata | null>(null);
const nombreNueva = ref('');
const buscando = ref(false);
const confirmando = ref(false);
const error = ref('');
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

const descripcion = computed(() =>
  props.nIds.length === 1 ? '1 Botella' : `${props.nIds.length} Botellas seleccionadas`,
);

const puedeConfirmar = computed(() =>
  modo.value === 'existente' ? seleccionada.value !== null : nombreNueva.value.trim().length > 0,
);

function onSearchInput(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => void buscar(), 300);
}

async function buscar(): Promise<void> {
  if (!query.value.trim()) {
    resultados.value = [];
    return;
  }
  buscando.value = true;
  error.value = '';
  try {
    const params = new URLSearchParams({ q: query.value.trim(), limit: '10' });
    const res = await fetch(`/api/infra/camaras/buscar?${params}`, { credentials: 'include' });
    const data = await res.json() as { error?: string; camaras?: CamaraCandidata[] };
    if (!res.ok) throw new Error(data.error ?? `Error ${res.status}`);
    resultados.value = data.camaras ?? [];
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'No se pudo buscar cámaras.';
  } finally {
    buscando.value = false;
  }
}

function resetState(): void {
  modo.value = 'existente';
  query.value = '';
  resultados.value = [];
  seleccionada.value = null;
  nombreNueva.value = '';
  error.value = '';
}

function handleClose(): void {
  dialogEl.value?.close();
  resetState();
  emit('close');
}

async function handleConfirmar(): Promise<void> {
  if (!puedeConfirmar.value) return;
  confirmando.value = true;
  error.value = '';
  try {
    const res = await fetch('/api/infra/cromo-botellas/asociar', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        n_ids: props.nIds,
        camara_id: modo.value === 'existente' ? seleccionada.value?.id : undefined,
        nombre_nueva_camara: modo.value === 'nueva' ? nombreNueva.value.trim() : undefined,
        csrf_token: csrf(),
      }),
    });
    const data = await res.json() as {
      error?: string;
      ok?: boolean;
      camara_id?: number;
      camara_creada?: boolean;
      botellas_vinculadas?: number;
    };
    if (!res.ok || !data.ok) throw new Error(data.error ?? 'No se pudo asociar la Botella.');
    emit('asociada', {
      camaraId: data.camara_id ?? 0,
      camaraCreada: data.camara_creada ?? false,
      botellasVinculadas: data.botellas_vinculadas ?? props.nIds.length,
    });
    handleClose();
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'No se pudo asociar la Botella.';
  } finally {
    confirmando.value = false;
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      resetState();
      dialogEl.value?.showModal();
      return;
    }
    if (dialogEl.value?.open) {
      dialogEl.value.close();
    }
  },
);
</script>

<style scoped>
.asociar-modal {
  width: min(520px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.asociar-modal::backdrop {
  background: rgba(4, 8, 14, 0.74);
  backdrop-filter: blur(8px);
}

.modal-content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--text);
  box-shadow: var(--shadow-lg);
}

.asociar-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.asociar-tabs {
  display: flex;
  gap: 4px;
  margin-bottom: 14px;
  border-radius: 8px;
  background: var(--color-bg);
  padding: 3px;
}

.asociar-tab {
  flex: 1;
  padding: 6px 10px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 0.82rem;
}

.asociar-tab.active {
  background: var(--color-brand-primary-soft);
  color: var(--color-accent-200);
}

.asociar-search {
  width: 100%;
  padding: 8px 12px;
  margin-bottom: 10px;
  border: 1px solid var(--color-divider);
  border-radius: 8px;
  background: var(--color-bg);
  color: var(--text);
}

.asociar-hint {
  font-size: 0.8rem;
  color: var(--muted);
  margin: 0 0 10px;
}

.asociar-empty {
  padding: 12px;
  border-radius: 10px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  font-size: 0.85rem;
  text-align: center;
  margin-bottom: 10px;
}

.asociar-empty.error {
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
}

.asociar-results {
  list-style: none;
  margin: 0 0 10px;
  padding: 0;
  max-height: 240px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.asociar-result-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  cursor: pointer;
}

.asociar-result-item:hover {
  border-color: var(--color-accent);
}

.asociar-result-meta {
  font-size: 0.72rem;
  color: var(--muted);
}

.asociar-seleccion {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  margin-bottom: 10px;
  font-size: 0.85rem;
}

.asociar-actions {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}
</style>
