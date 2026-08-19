<!--
  Nombre de archivo: ModalConfirmarAccionMasiva.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalConfirmarAccionMasiva.vue
  Descripción: Confirmación genérica para una acción masiva sobre todos los grupos detectados (fusión de Cámaras, apropiación de Botellas) — puramente presentacional, el padre maneja la llamada real
-->
<template>
  <dialog ref="dialogEl" class="unificar-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="unificar-title-row">
        <strong>{{ titulo }}</strong>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <p class="unificar-hint">{{ mensaje }}</p>

      <div v-if="resultado" class="accion-masiva-resultado">{{ resultado }}</div>
      <div v-if="error" class="unificar-empty error">{{ error }}</div>

      <div class="unificar-actions">
        <button class="btn primary" type="button" :disabled="confirmando" @click="$emit('confirm')">
          {{ confirmando ? 'Procesando...' : 'Confirmar' }}
        </button>
        <button class="btn subtle" type="button" :disabled="confirmando" @click="handleClose">
          {{ resultado ? 'Cerrar' : 'Cancelar' }}
        </button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

const props = defineProps<{
  open: boolean;
  titulo: string;
  mensaje: string;
  confirmando: boolean;
  error: string;
  resultado: string | null;
}>();

const emit = defineEmits<{
  close: [];
  confirm: [];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
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
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--text);
  box-shadow: var(--shadow-lg);
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

.unificar-empty {
  padding: 14px;
  border-radius: 10px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  font-size: 0.85rem;
  text-align: center;
  margin-bottom: 14px;
}

.unificar-empty.error {
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
}

.accion-masiva-resultado {
  padding: 12px 14px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--success) 14%, transparent);
  color: var(--success);
  font-size: 0.85rem;
  margin-bottom: 14px;
}

.unificar-actions {
  display: flex;
  gap: 10px;
}
</style>
