<!--
  Nombre de archivo: ServiciosCambioCategoriaModal.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ServiciosCambioCategoriaModal.vue
  Descripción: Modal de confirmación para el cambio de categoría masivo de Servicios
-->
<template>
  <dialog ref="dialogEl" class="categoria-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="categoria-title-row">
        <strong>Cambiar Nivel Cliente</strong>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <p class="categoria-texto">
        Se cambiará el Nivel Cliente a <strong>{{ categoriaLabel(categoria) }}</strong> para
        <strong>{{ servicioIds.length }}</strong> servicio{{ servicioIds.length !== 1 ? 's' : '' }} seleccionado{{ servicioIds.length !== 1 ? 's' : '' }}.
      </p>

      <p class="categoria-aviso">
        El cambio crea una <strong>excepción</strong> en cada servicio: dejan de heredar la categoría de su
        cliente hasta que se use "Heredar del cliente" en su detalle.
      </p>

      <div v-if="error" class="categoria-empty error">{{ error }}</div>

      <div class="categoria-actions">
        <button class="btn primary" type="button" :disabled="aplicando" @click="handleConfirmar">
          {{ aplicando ? 'Aplicando...' : 'Confirmar' }}
        </button>
        <button class="btn subtle" type="button" :disabled="aplicando" @click="handleClose">Cancelar</button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { categoriaLabel, updateServiciosCategoriaMasivo } from '../../api/servicios';

const props = defineProps<{
  open: boolean;
  servicioIds: number[];
  categoria: number;
}>();

const emit = defineEmits<{
  close: [];
  aplicada: [payload: { actualizados: number; noEncontrados: number[] }];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const aplicando = ref(false);
const error = ref('');

function resetState(): void {
  error.value = '';
}

function handleClose(): void {
  dialogEl.value?.close();
  resetState();
  emit('close');
}

async function handleConfirmar(): Promise<void> {
  if (props.servicioIds.length === 0 || aplicando.value) return;
  aplicando.value = true;
  error.value = '';
  try {
    const respuesta = await updateServiciosCategoriaMasivo(props.servicioIds, props.categoria);
    emit('aplicada', { actualizados: respuesta.actualizados, noEncontrados: respuesta.no_encontrados });
    handleClose();
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo cambiar el Nivel Cliente.';
  } finally {
    aplicando.value = false;
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
.categoria-modal {
  width: min(420px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.categoria-modal::backdrop {
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

.categoria-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
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
  color: var(--text);
}

.categoria-texto {
  margin: 0 0 14px;
  font-size: 0.88rem;
  line-height: 1.5;
  color: var(--text);
}

.categoria-aviso {
  margin: 0 0 14px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 0.82rem;
  line-height: 1.5;
  background: color-mix(in srgb, var(--warning) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--warning) 33%, transparent);
  color: var(--color-text);
}

.categoria-empty {
  padding: 12px;
  border-radius: 10px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  font-size: 0.85rem;
  text-align: center;
  margin-bottom: 10px;
}

.categoria-empty.error {
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
}

.categoria-actions {
  display: flex;
  gap: 10px;
  margin-top: 4px;
}
</style>
