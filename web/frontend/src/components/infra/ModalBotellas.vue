<!--
  Nombre de archivo: ModalBotellas.vue
  Ubicación de archivo: web/frontend/src/components/infra/ModalBotellas.vue
  Descripción: Modal con las Botellas (jerarquía Cámara/Botella) de una cámara, cada una como tarjeta independiente
-->
<template>
  <dialog ref="dialogEl" class="infra-detail-modal" @click.self="handleClose">
    <section class="infra-detail-modal__content">
      <header class="infra-detail-modal__header">
        <div>
          <p class="infra-detail-modal__eyebrow">Botellas</p>
          <h3>{{ camaraNombre }} · ID {{ camaraId ?? '—' }}</h3>
        </div>
        <button class="close-btn" type="button" @click="handleClose">×</button>
      </header>

      <div v-if="botellas.length === 0" class="infra-detail-empty">
        Esta cámara no tiene botellas registradas.
      </div>
      <div v-else class="botellas-grid">
        <RouterLink
          v-for="botella in botellas"
          :key="botella.id"
          :to="`/infra/Camaras/${botella.id}`"
          class="botella-card"
          @click="handleClose"
        >
          <div class="botella-card__row">
            <span :class="['botella-card__dot', estadoDotClass(botella.estado)]" aria-hidden="true"></span>
            <span class="botella-card__estado">{{ botella.estado || 'LIBRE' }}</span>
            <span class="botella-card__id">ID {{ botella.id }}</span>
          </div>
          <strong class="botella-card__nombre">{{ botella.nombre || `Botella ${botella.id}` }}</strong>
          <span class="botella-card__meta">
            {{ botella.servicios.length }} servicio{{ botella.servicios.length !== 1 ? 's' : '' }}
          </span>
        </RouterLink>
      </div>
    </section>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { RouterLink } from 'vue-router';

interface BotellaItem {
  id: number;
  nombre: string | null;
  estado: string | null;
  servicios: string[];
}

const props = defineProps<{
  open: boolean;
  camaraId: number | null;
  camaraNombre: string;
  botellas: BotellaItem[];
}>();

const emit = defineEmits<{ close: [] }>();
const dialogEl = ref<HTMLDialogElement | null>(null);

function handleClose(): void {
  dialogEl.value?.close();
  emit('close');
}

function estadoDotClass(estado: string | null): string {
  const value = (estado || 'LIBRE').toLowerCase();
  return ['libre', 'ocupada', 'baneada', 'detectada'].includes(value) ? value : 'libre';
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
  width: min(720px, calc(100vw - 32px));
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

.infra-detail-empty {
  padding: 18px;
  border-radius: 14px;
  border: 1px dashed rgba(148, 163, 184, 0.24);
  color: var(--muted);
  background: rgba(15, 23, 42, 0.45);
}

.botellas-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}

.botella-card {
  display: grid;
  gap: 8px;
  padding: 14px 16px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(148, 163, 184, 0.14);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.botella-card:hover {
  border-color: rgba(96, 165, 250, 0.4);
  transform: translateY(-2px);
}

.botella-card__row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.botella-card__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
  flex: none;
}

.botella-card__dot.libre { background: #34d399; }
.botella-card__dot.ocupada { background: #facc15; }
.botella-card__dot.baneada { background: #f87171; }
.botella-card__dot.detectada { background: #60a5fa; }

.botella-card__estado {
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
}

.botella-card__id {
  margin-left: auto;
  font-size: 0.7rem;
  color: var(--muted);
}

.botella-card__nombre {
  font-size: 0.92rem;
  color: #f8fafc;
  word-break: break-word;
}

.botella-card__meta {
  font-size: 0.78rem;
  color: var(--muted);
}
</style>
