<!--
  Nombre de archivo: ModalAlias.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalAlias.vue
  Descripción: Modal aislado para visualizar los alias conocidos de una cámara
-->
<template>
  <dialog ref="dialogEl" class="infra-detail-modal" @click.self="handleClose">
    <section class="infra-detail-modal__content">
      <header class="infra-detail-modal__header">
        <div>
          <p class="infra-detail-modal__eyebrow">Alias Conocidos</p>
          <h3>{{ camaraNombre }} · ID {{ camaraId ?? '—' }}</h3>
        </div>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </header>

      <div v-if="aliases.length === 0" class="infra-detail-empty">
        No hay alias registrados para esta cámara.
      </div>
      <ul v-else class="infra-detail-list">
        <li v-for="alias in aliases" :key="alias.id" class="infra-detail-list__item">
          <strong>{{ alias.nombre }}</strong>
          <span>{{ formatFecha(alias.created_at) }}</span>
        </li>
      </ul>
    </section>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';

interface AliasItem {
  id: number;
  nombre: string;
  created_at: string | null;
}

const props = defineProps<{
  open: boolean;
  camaraId: number | null;
  camaraNombre: string;
  aliases: AliasItem[];
}>();

const emit = defineEmits<{ close: [] }>();
const dialogEl = ref<HTMLDialogElement | null>(null);

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

function formatFecha(value: string | null): string {
  if (!value) return 'Sin fecha registrada';
  return new Date(value).toLocaleString('es-AR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
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
.infra-detail-modal {
  width: min(560px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.infra-detail-modal::backdrop {
  background: rgba(4, 8, 14, 0.74);
  backdrop-filter: blur(8px);
}

.infra-detail-modal__content {
  background: linear-gradient(180deg, rgba(17, 24, 39, 0.98), rgba(9, 14, 23, 0.98));
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 18px;
  padding: 24px;
  color: var(--text);
  box-shadow: 0 28px 60px rgba(0, 0, 0, 0.35);
}

.infra-detail-modal__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}

.infra-detail-modal__header h3 {
  margin: 6px 0 0;
  font-size: 1.3rem;
}

.infra-detail-modal__eyebrow {
  margin: 0;
  color: #7dd3fc;
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.infra-detail-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 12px;
}

.infra-detail-list__item {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

.infra-detail-list__item span {
  color: var(--muted);
  font-size: 0.82rem;
  text-align: right;
}

.infra-detail-empty {
  padding: 18px;
  border-radius: 14px;
  border: 1px dashed rgba(148, 163, 184, 0.24);
  color: var(--muted);
  background: rgba(15, 23, 42, 0.45);
}
</style>