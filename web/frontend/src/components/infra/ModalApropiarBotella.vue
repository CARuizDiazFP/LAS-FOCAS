<!--
  Nombre de archivo: ModalApropiarBotella.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalApropiarBotella.vue
  Descripción: Confirmación de apropiación legado→Cromo de un par de Botellas duplicadas ya resuelto (sin paso de búsqueda)
-->
<template>
  <dialog ref="dialogEl" class="unificar-modal" @click.self="handleClose">
    <div class="modal-content">
      <div class="unificar-title-row">
        <strong>Apropiar Botella duplicada</strong>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </div>

      <div class="unificar-confirmacion">
        <div class="unificar-confirmacion-row">
          <span class="unificar-badge principal">Cromo (se conserva)</span>
          <strong>{{ cromoNombre }}</strong>
        </div>
        <div class="unificar-confirmacion-row">
          <span class="unificar-badge secundaria">Legado (se elimina tras transferir todo)</span>
          <strong>{{ legadoNombre }}</strong>
        </div>
        <p class="unificar-hint">
          La Botella Cromo se conserva sin cambios. La Botella legado se eliminará luego de reasignar
          sus datos reales — Cables, Empalmes, Ingresos, alias e historial de auditoría — a la Cámara
          padre <strong>{{ camaraPadreNombre }}</strong>.
        </p>
      </div>

      <div v-if="error" class="unificar-empty error">{{ error }}</div>

      <div class="unificar-actions">
        <button class="btn primary" type="button" :disabled="confirmando" @click="handleConfirmar">
          {{ confirmando ? 'Apropiando...' : 'Confirmar apropiación' }}
        </button>
        <button class="btn subtle" type="button" :disabled="confirmando" @click="handleClose">Cancelar</button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

import { apropiarBotellaLegadoACromo } from '../../api/botellas';

const props = defineProps<{
  open: boolean;
  legadoId: number | null;
  legadoNombre: string;
  cromoNId: number | null;
  cromoNombre: string;
  camaraPadreNombre: string;
}>();

const emit = defineEmits<{
  close: [];
  apropiada: [];
  error: [message: string];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const confirmando = ref(false);
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
  if (props.legadoId == null || props.cromoNId == null) return;
  confirmando.value = true;
  error.value = '';
  try {
    const data = await apropiarBotellaLegadoACromo(props.legadoId, props.cromoNId);
    if (!data.ok) throw new Error('No se pudo apropiar la Botella.');
    emit('apropiada');
    handleClose();
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : 'No se pudo apropiar la Botella.';
    error.value = message;
    emit('error', message);
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
  margin: 0;
}

.unificar-empty {
  padding: 14px;
  border-radius: 10px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  font-size: 0.85rem;
  text-align: center;
  margin-top: 12px;
}

.unificar-empty.error {
  border-color: color-mix(in srgb, var(--error) 40%, transparent);
  color: var(--error);
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
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
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
  background: color-mix(in srgb, var(--success) 18%, transparent);
  color: var(--success);
}

.unificar-badge.secundaria {
  background: color-mix(in srgb, var(--warning) 16%, transparent);
  color: var(--warning);
}

.unificar-actions {
  display: flex;
  gap: 10px;
}
</style>
