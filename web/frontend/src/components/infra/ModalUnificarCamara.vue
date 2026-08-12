<!--
  Nombre de archivo: ModalUnificarCamara.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalUnificarCamara.vue
  Descripción: Modal para unificar la Cámara actual (principal) con una Cámara duplicada (secundaria) — la secundaria pasa a ser Botella de la principal
-->
<template>
  <dialog ref="dialogEl" class="unificar-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="unificar-title-row">
        <strong>Unificar con Cámara duplicada</strong>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <p class="unificar-hint">
        <strong>{{ camaraNombre || `Cámara ${camaraId ?? ''}` }}</strong> absorberá a la Cámara que
        elijas: sus Botellas, servicios y rutas quedan bajo esta Cámara, y su nombre pasa a ser un
        alias. No se elimina ningún dato — la Cámara elegida conserva su historial completo.
      </p>

      <template v-if="!seleccionada">
        <input
          v-model="query"
          type="text"
          placeholder="Buscar Cámara duplicada por nombre..."
          class="unificar-search"
          @input="onSearchInput"
        />

        <div v-if="buscando" class="unificar-empty">Buscando...</div>
        <div v-else-if="error" class="unificar-empty error">{{ error }}</div>
        <div v-else-if="query.trim() && resultados.length === 0" class="unificar-empty">
          Ninguna Cámara coincide con "{{ query }}".
        </div>
        <ul v-else-if="resultados.length" class="unificar-results">
          <li
            v-for="candidata in resultados"
            :key="candidata.id"
            class="unificar-result-item"
            @click="seleccionada = candidata"
          >
            <strong>{{ candidata.nombre }}</strong>
            <span class="unificar-result-meta">
              ID {{ candidata.id }} · {{ candidata.estado }} · {{ candidata.botellas_count }} botella{{ candidata.botellas_count !== 1 ? 's' : '' }}
            </span>
          </li>
        </ul>
      </template>

      <template v-else>
        <div class="unificar-confirmacion">
          <div class="unificar-confirmacion-row">
            <span class="unificar-badge principal">Principal (conserva la identidad)</span>
            <strong>{{ camaraNombre }}</strong>
          </div>
          <div class="unificar-confirmacion-row">
            <span class="unificar-badge secundaria">Secundaria (pasa a ser Botella + alias)</span>
            <strong>{{ seleccionada.nombre }}</strong>
          </div>
          <p v-if="seleccionada.botellas_count > 0" class="unificar-hint">
            Esta Cámara ya tiene {{ seleccionada.botellas_count }} Botella{{ seleccionada.botellas_count !== 1 ? 's' : '' }} propia{{ seleccionada.botellas_count !== 1 ? 's' : '' }} — también pasarán a ser Botellas de {{ camaraNombre }}.
          </p>
        </div>

        <div v-if="error" class="unificar-empty error">{{ error }}</div>

        <div class="unificar-actions">
          <button class="btn primary" type="button" :disabled="confirmando" @click="handleConfirmar">
            {{ confirmando ? 'Unificando...' : 'Confirmar unificación' }}
          </button>
          <button class="btn subtle" type="button" :disabled="confirmando" @click="seleccionada = null">Volver a buscar</button>
        </div>
      </template>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
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
  camaraId: number | null;
  camaraNombre: string;
}>();

const emit = defineEmits<{
  close: [];
  merged: [];
}>();

const { csrf } = useSession();
const dialogEl = ref<HTMLDialogElement | null>(null);
const query = ref('');
const resultados = ref<CamaraCandidata[]>([]);
const seleccionada = ref<CamaraCandidata | null>(null);
const buscando = ref(false);
const confirmando = ref(false);
const error = ref('');
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

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
    if (props.camaraId != null) params.set('excluir_id', String(props.camaraId));
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
  query.value = '';
  resultados.value = [];
  seleccionada.value = null;
  error.value = '';
}

function handleClose(): void {
  dialogEl.value?.close();
  resetState();
  emit('close');
}

async function handleConfirmar(): Promise<void> {
  if (!props.camaraId || !seleccionada.value) return;
  confirmando.value = true;
  error.value = '';
  try {
    const res = await fetch('/api/infra/camaras/merge', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        camara_principal_id: props.camaraId,
        camara_secundaria_id: seleccionada.value.id,
        csrf_token: csrf(),
      }),
    });
    const data = await res.json() as { error?: string; ok?: boolean };
    if (!res.ok || !data.ok) throw new Error(data.error ?? 'No se pudo unificar las cámaras.');
    emit('merged');
    handleClose();
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'No se pudo unificar las cámaras.';
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
.unificar-modal {
  width: min(560px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.unificar-modal::backdrop {
  background: rgba(4, 8, 14, 0.74);
  backdrop-filter: blur(8px);
}

.modal-content {
  background: linear-gradient(180deg, rgba(17, 24, 39, 0.98), rgba(9, 14, 23, 0.98));
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 18px;
  padding: 24px;
  color: var(--text);
  box-shadow: 0 28px 60px rgba(0, 0, 0, 0.35);
}

.unificar-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.unificar-hint {
  font-size: 0.85rem;
  color: var(--muted);
  line-height: 1.5;
  margin: 0 0 14px;
}

.unificar-search {
  width: 100%;
  padding: 8px 12px;
  margin-bottom: 12px;
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.6);
  color: var(--text);
}

.unificar-empty {
  padding: 14px;
  border-radius: 10px;
  border: 1px dashed rgba(148, 163, 184, 0.24);
  color: var(--muted);
  font-size: 0.85rem;
  text-align: center;
}

.unificar-empty.error {
  border-color: rgba(239, 68, 68, 0.4);
  color: #fecaca;
}

.unificar-results {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 280px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.unificar-result-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.14);
  cursor: pointer;
  transition: border-color 0.15s ease;
}

.unificar-result-item:hover {
  border-color: rgba(96, 165, 250, 0.4);
}

.unificar-result-meta {
  font-size: 0.75rem;
  color: var(--muted);
}

.unificar-confirmacion {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 14px;
}

.unificar-confirmacion-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.unificar-badge {
  display: inline-flex;
  align-self: flex-start;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 0.68rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.unificar-badge.principal {
  background: rgba(16, 185, 129, 0.18);
  color: #bbf7d0;
}

.unificar-badge.secundaria {
  background: rgba(250, 204, 21, 0.16);
  color: #fde68a;
}

.unificar-actions {
  display: flex;
  gap: 10px;
}
</style>
