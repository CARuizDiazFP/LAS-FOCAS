<!--
  Nombre de archivo: ModalVerificadorCromo.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalVerificadorCromo.vue
  Descripción: Modal de sólo lectura con la data EN VIVO de un elemento Cromo por n_id (nunca persiste nada)
-->
<template>
  <dialog ref="dialogEl" class="cromo-vivo-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="cromo-vivo-title-row">
        <strong>Elemento Cromo <code>{{ nId }}</code></strong>
        <span v-if="elemento?.clase_etiqueta || elemento?.clase_entidad" class="cromo-vivo-badge">
          {{ elemento.clase_etiqueta || elemento.clase_entidad }}
        </span>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <div v-if="loading" class="cromo-vivo-empty">Consultando Cromo en vivo...</div>
      <div v-else-if="errorMessage" class="cromo-vivo-empty error">{{ errorMessage }}</div>
      <template v-else-if="elemento">
        <div class="cromo-vivo-destacado">
          <div>
            <span class="cromo-vivo-destacado__etiqueta">Nombre</span>
            <p class="cromo-vivo-destacado__valor">{{ elemento.nombre || '—' }}</p>
          </div>
          <div v-if="elemento.notas">
            <span class="cromo-vivo-destacado__etiqueta">Notas</span>
            <p class="cromo-vivo-destacado__valor">{{ elemento.notas }}</p>
          </div>
        </div>

        <p v-if="elemento.atributos.length === 0" class="hint">
          Cromo no devolvió atributos adicionales para este elemento.
        </p>
        <dl v-else class="cromo-vivo-meta">
          <div v-for="atributo in elemento.atributos" :key="atributo.id">
            <dt>{{ atributo.etiqueta }}</dt>
            <dd>{{ atributo.valor ?? '—' }}</dd>
          </div>
        </dl>

        <details class="cromo-vivo-crudo">
          <summary>Ver payload crudo</summary>
          <pre>{{ JSON.stringify(elemento.payload_raw, null, 2) }}</pre>
        </details>
      </template>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

import { ApiError } from '../../api/client';
import { obtenerElementoVivoCromo, type CromoElementoVivo } from '../../api/cromo';

const props = defineProps<{
  open: boolean;
  nId: number | null;
}>();

const emit = defineEmits<{
  close: [];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const elemento = ref<CromoElementoVivo | null>(null);
const loading = ref(false);
const errorMessage = ref('');

async function cargarElemento(): Promise<void> {
  if (!props.nId) {
    return;
  }
  loading.value = true;
  errorMessage.value = '';
  elemento.value = null;
  try {
    elemento.value = await obtenerElementoVivoCromo(props.nId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      errorMessage.value = `No existe un elemento con n_id=${props.nId} en Cromo.`;
    } else if (e instanceof ApiError && e.status === 502) {
      errorMessage.value = 'Cromo no respondió. Probá de nuevo en un momento.';
    } else {
      errorMessage.value = e instanceof Error ? e.message : 'Error consultando Cromo en vivo.';
    }
  } finally {
    loading.value = false;
  }
}

function handleClose(): void {
  dialogEl.value?.close();
  elemento.value = null;
  errorMessage.value = '';
  emit('close');
}

watch(
  () => props.open,
  async (isOpen) => {
    if (!isOpen) {
      if (dialogEl.value?.open) {
        dialogEl.value.close();
      }
      return;
    }
    dialogEl.value?.showModal();
    await cargarElemento();
  },
);
</script>

<style scoped>
.cromo-vivo-modal {
  width: min(680px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.cromo-vivo-modal::backdrop {
  background: rgba(4, 8, 14, 0.78);
  backdrop-filter: blur(10px);
}

.modal-content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--color-text);
  box-shadow: var(--shadow-lg);
  max-height: calc(100vh - 64px);
  overflow-y: auto;
}

.cromo-vivo-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.cromo-vivo-title-row strong {
  font-size: 1.1rem;
  color: var(--color-text);
}

.close-btn {
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.4rem;
  line-height: 1;
}

.close-btn:hover {
  color: var(--color-text);
}

.cromo-vivo-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  color: var(--color-accent);
}

.cromo-vivo-empty {
  padding: 16px;
  border-radius: 14px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  background: var(--color-bg);
}

.cromo-vivo-empty.error {
  color: var(--error);
}

.cromo-vivo-destacado {
  display: grid;
  gap: 14px;
  margin-bottom: 18px;
  padding: 16px;
  border-radius: 14px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
}

.cromo-vivo-destacado__etiqueta {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}

.cromo-vivo-destacado__valor {
  margin: 4px 0 0;
  font-size: 15px;
  word-break: break-word;
}

.cromo-vivo-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  margin: 0 0 14px;
}

.cromo-vivo-meta div {
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  padding: 8px 11px;
}

.cromo-vivo-meta dt {
  font-size: 11px;
  color: var(--muted);
}

.cromo-vivo-meta dd {
  font-size: 13.5px;
  font-weight: 500;
  margin: 2px 0 0;
  word-break: break-word;
}

.cromo-vivo-crudo {
  margin-top: 6px;
}

.cromo-vivo-crudo summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--muted);
}

.cromo-vivo-crudo pre {
  margin-top: 10px;
  padding: 12px;
  border-radius: 10px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  font-size: 11.5px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.hint {
  font-size: 0.8rem;
  color: var(--muted);
}

@media (max-width: 720px) {
  .modal-content {
    padding: 20px;
  }
}
</style>
