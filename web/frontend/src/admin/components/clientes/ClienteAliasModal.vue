<!--
  Nombre de archivo: ClienteAliasModal.vue
  Ubicación de archivo: web/frontend/src/admin/components/clientes/ClienteAliasModal.vue
  Descripción: Modal de alias (nombres alternativos) de un cliente — listar, agregar y quitar los no canónicos
-->
<template>
  <dialog ref="dialogEl" class="clientes-modal" @click.self="handleClose">
    <div class="clientes-modal__content">
      <div class="clientes-modal__title-row">
        <strong>Alias de {{ cliente?.nombre ?? 'cliente' }}</strong>
        <button class="clientes-modal__close" type="button" aria-label="Cerrar" @click="handleClose">×</button>
      </div>

      <p class="clientes-modal__hint">
        Cada alias es una grafía del nombre del cliente en los servicios. Todos comparten la categoría del cliente.
        El alias canónico no se puede quitar.
      </p>

      <ul v-if="cliente && cliente.alias.length > 0" class="alias-lista">
        <li v-for="alias in cliente.alias" :key="alias.id" class="alias-lista__item">
          <span class="alias-lista__nombre">{{ alias.nombre_original }}</span>
          <span v-if="alias.canonico" class="alias-lista__tag">Canónico</span>
          <span v-else class="alias-lista__tag is-muted">{{ alias.origen === 'MANUAL' ? 'Manual' : 'Auto' }}</span>
          <button
            v-if="!alias.canonico"
            class="btn danger alias-lista__quitar"
            type="button"
            :disabled="ocupado"
            @click="quitar(alias.id)"
          >
            Quitar
          </button>
        </li>
      </ul>
      <p v-else class="clientes-modal__hint">El cliente no tiene alias.</p>

      <form class="alias-form" @submit.prevent="agregar">
        <input
          v-model="nuevoAlias"
          class="alias-form__input"
          type="text"
          placeholder="Nombre alternativo, tal como figura en los servicios"
          :disabled="ocupado"
        />
        <button class="btn primary" type="submit" :disabled="ocupado || !nuevoAlias.trim()">
          {{ ocupado ? 'Guardando...' : 'Agregar alias' }}
        </button>
      </form>

      <p v-if="error" class="clientes-modal__error">{{ error }}</p>

      <div class="clientes-modal__actions">
        <button class="btn subtle" type="button" @click="handleClose">Cerrar</button>
      </div>
    </div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

import { agregarAliasCliente, quitarAliasCliente, type ClienteCategoria } from '../../api/clientesCategoria';

const props = defineProps<{
  open: boolean;
  cliente: ClienteCategoria | null;
}>();

const emit = defineEmits<{
  close: [];
  /** Se agregó o quitó un alias: el padre recarga el listado. */
  cambiado: [];
}>();

const dialogEl = ref<HTMLDialogElement | null>(null);
const nuevoAlias = ref('');
const ocupado = ref(false);
const error = ref('');

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

async function agregar(): Promise<void> {
  const nombre = nuevoAlias.value.trim();
  if (!props.cliente || !nombre || ocupado.value) return;
  ocupado.value = true;
  error.value = '';
  try {
    await agregarAliasCliente(props.cliente.id, nombre);
    nuevoAlias.value = '';
    emit('cambiado');
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo agregar el alias.';
  } finally {
    ocupado.value = false;
  }
}

async function quitar(aliasId: number): Promise<void> {
  if (ocupado.value) return;
  ocupado.value = true;
  error.value = '';
  try {
    await quitarAliasCliente(aliasId);
    emit('cambiado');
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo quitar el alias.';
  } finally {
    ocupado.value = false;
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      nuevoAlias.value = '';
      error.value = '';
      dialogEl.value?.showModal();
      return;
    }
    if (dialogEl.value?.open) dialogEl.value.close();
  },
);
</script>

<style scoped>
.clientes-modal {
  width: min(560px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.clientes-modal::backdrop {
  background: rgba(4, 8, 14, 0.74);
  backdrop-filter: blur(8px);
}

.clientes-modal__content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--color-text);
  box-shadow: var(--shadow-lg);
}

.clientes-modal__title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.clientes-modal__close {
  border: none;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  font-size: 1.4rem;
  line-height: 1;
}

.clientes-modal__close:hover {
  color: var(--color-text);
}

.clientes-modal__hint {
  margin: 0 0 14px;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--muted);
}

.clientes-modal__error {
  margin: 0 0 12px;
  font-size: 0.85rem;
  color: var(--error);
}

.clientes-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.alias-lista {
  list-style: none;
  margin: 0 0 14px;
  padding: 0;
  display: grid;
  gap: 6px;
  max-height: 320px;
  overflow-y: auto;
}

.alias-lista__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-divider);
  background: var(--color-bg);
  font-size: 0.85rem;
}

.alias-lista__nombre {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}

.alias-lista__tag {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 0.7rem;
  background: var(--color-brand-primary-soft);
  color: var(--color-accent-200);
  white-space: nowrap;
}

.alias-lista__tag.is-muted {
  background: color-mix(in srgb, var(--color-state-idle) 18%, transparent);
  color: var(--muted);
}

.alias-lista__quitar {
  min-height: 26px;
  padding: 2px 10px;
  font-size: 0.75rem;
}

.alias-form {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.alias-form__input {
  flex: 1;
  min-width: 0;
  padding: 7px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-divider);
  background: var(--color-bg);
  color: var(--color-text);
  font-size: 0.85rem;
}
</style>
