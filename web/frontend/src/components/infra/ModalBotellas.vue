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
          :key="`${botella.origen}:${botella.id}`"
          :to="botellaDetailPath(botella.origen, botella.id)"
          class="botella-card"
          @click="handleClose"
        >
          <div class="botella-card__row">
            <span :class="['botella-card__origen', `is-${botella.origen}`]">{{ botella.origen === 'cromo' ? 'Cromo' : 'Legado' }}</span>
            <span v-if="botella.estado" :class="['botella-card__dot', estadoDotClass(botella.estado)]" aria-hidden="true"></span>
            <span class="botella-card__estado">{{ botella.estado || 'Sin estado operativo' }}</span>
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

import type { BotellaOrigen } from '../../api/botellas';
import { botellaDetailPath } from '../../utils/botellaLinks';

interface BotellaItem {
  id: number;
  nombre: string | null;
  estado: string | null;
  servicios: string[];
  origen: BotellaOrigen;
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
  return ['libre', 'ocupada', 'baneada', 'detectada', 'no_operativa'].includes(value) ? value : 'libre';
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
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 24px;
  color: var(--text);
  box-shadow: var(--shadow-lg);
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
  color: var(--color-accent);
  font-size: 0.76rem;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.infra-detail-empty {
  padding: 18px;
  border-radius: 14px;
  border: 1px dashed var(--color-divider);
  color: var(--muted);
  background: var(--color-bg);
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
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.botella-card:hover {
  border-color: var(--color-accent);
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
  background: var(--color-state-idle);
  flex: none;
}

.botella-card__dot.libre { background: var(--color-state-ok); }
.botella-card__dot.ocupada { background: var(--color-state-warn); }
.botella-card__dot.baneada { background: var(--color-state-error); }
.botella-card__dot.detectada { background: var(--color-accent); }
.botella-card__dot.no_operativa { background: var(--color-state-idle); }

.botella-card__origen {
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 0.62rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: color-mix(in srgb, var(--color-neutral-400) 16%, transparent);
  color: var(--color-neutral-300);
}

.botella-card__origen.is-cromo {
  background: var(--color-brand-primary-soft);
  color: var(--color-accent-200);
}

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
  color: var(--color-text);
  word-break: break-word;
}

.botella-card__meta {
  font-size: 0.78rem;
  color: var(--muted);
}
</style>
