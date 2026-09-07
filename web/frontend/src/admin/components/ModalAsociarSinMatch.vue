<!--
  Nombre de archivo: ModalAsociarSinMatch.vue
  Ubicación de archivo: web/frontend/src/admin/components/ModalAsociarSinMatch.vue
  Descripción: Modal para asociar uno o más nombres sin match de la ingesta de Excel a una Cámara/Botella ya existente
-->
<template>
  <dialog ref="dialogEl" class="asociar-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="asociar-title-row">
        <strong>Asociar {{ casos.length === 1 ? '1 nombre' : `${casos.length} nombres` }} a una Cámara</strong>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <p class="asociar-hint">Nombres del Excel que se van a vincular:</p>
      <ul class="asociar-casos-lista">
        <li v-for="caso in casos" :key="caso.caso_id">{{ caso.nombre }}</li>
      </ul>

      <label class="asociar-label" for="asociar-sin-match-motivo">Motivo del baneo</label>
      <textarea
        id="asociar-sin-match-motivo"
        v-model="motivo"
        class="asociar-textarea"
        rows="2"
        maxlength="500"
        placeholder="Ej: Corte programado en zona norte — OT-2026-07-27"
        :disabled="confirmando"
      ></textarea>

      <input
        v-if="!seleccionada"
        v-model="query"
        type="text"
        placeholder="Buscar Cámara o Botella por nombre..."
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
            <span class="asociar-result-meta">
              ID {{ candidata.id }} · {{ candidata.estado }} · {{ descripcionCandidata(candidata) }}
            </span>
          </li>
        </ul>
      </div>
      <div v-else class="asociar-seleccion">
        <span>
          Destino elegido: <strong>{{ seleccionada.nombre }}</strong>
          <span class="asociar-result-meta"> · {{ descripcionCandidata(seleccionada) }}</span>
        </span>
        <button class="btn subtle" type="button" @click="seleccionada = null">Cambiar</button>
      </div>

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
import { asociarSinMatchCamaras, type AsociarSinMatchResponse } from '../../api/camaras';

interface CamaraCandidata {
  id: number;
  nombre: string;
  direccion: string | null;
  estado: string;
  botellas_count: number;
  cables_count: number;
  es_botella: boolean;
  camara_padre_id: number | null;
  camara_padre_nombre: string | null;
}

const props = defineProps<{
  open: boolean;
  casos: { caso_id: number; nombre: string }[];
  motivoSugerido: string;
}>();

const emit = defineEmits<{
  close: [];
  asociada: [resultado: AsociarSinMatchResponse];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const query = ref('');
const resultados = ref<CamaraCandidata[]>([]);
const seleccionada = ref<CamaraCandidata | null>(null);
const motivo = ref('');
const buscando = ref(false);
const confirmando = ref(false);
const error = ref('');
let debounceTimer: ReturnType<typeof setTimeout> | null = null;

const puedeConfirmar = computed(() => seleccionada.value !== null);

function descripcionCandidata(candidata: CamaraCandidata): string {
  return candidata.es_botella ? `Botella de "${candidata.camara_padre_nombre}"` : 'Cámara raíz';
}

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
    const params = new URLSearchParams({ q: query.value.trim(), limit: '10', solo_raiz: 'false' });
    const res = await fetch(`/api/infra/camaras/buscar?${params}`, { credentials: 'include' });
    const data = (await res.json()) as { error?: string; camaras?: CamaraCandidata[] };
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
  motivo.value = props.motivoSugerido;
  error.value = '';
}

function handleClose(): void {
  dialogEl.value?.close();
  resetState();
  emit('close');
}

async function handleConfirmar(): Promise<void> {
  if (!puedeConfirmar.value || !seleccionada.value) return;
  confirmando.value = true;
  error.value = '';
  try {
    const resultado = await asociarSinMatchCamaras(
      props.casos.map((c) => c.caso_id),
      seleccionada.value.id,
      motivo.value.trim() || undefined,
    );
    emit('asociada', resultado);
    handleClose();
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : 'No se pudo completar la asociación.';
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

.asociar-hint {
  font-size: 0.8rem;
  color: var(--muted);
  margin: 0 0 6px;
}

.asociar-casos-lista {
  list-style: none;
  margin: 0 0 14px;
  padding: 0;
  max-height: 120px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.85rem;
}

.asociar-casos-lista li {
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  word-break: break-word;
}

.asociar-label {
  font-size: 0.875rem;
  color: var(--muted);
  margin: 0 0 6px;
  display: block;
}

.asociar-textarea {
  width: 100%;
  background: var(--color-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-size: 0.9rem;
  padding: 10px 12px;
  resize: vertical;
  box-sizing: border-box;
  font-family: inherit;
  margin-bottom: 12px;
  transition: border-color 0.15s;
}

.asociar-textarea:focus {
  outline: none;
  border-color: var(--primary);
}

.asociar-textarea:disabled {
  opacity: 0.55;
  cursor: not-allowed;
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
  gap: 10px;
}

.asociar-actions {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}
</style>
