<!--
  Nombre de archivo: BotellaViewerCard.vue
  Ubicación de archivo: web/frontend/src/components/infra/BotellaViewerCard.vue
  Descripción: Tarjeta mínima de Botella (origen, estado) para el listado general dual del dashboard admin de Botellas
-->
<template>
  <article class="botella-viewer-card" role="button" tabindex="0" @click="goToDetail" @keyup.enter="goToDetail">
    <div class="botella-viewer-card__row">
      <span :class="['botella-viewer-card__dot', `is-${estadoToken}`]" :title="botella.estado ?? ''" aria-hidden="true"></span>
      <span class="botella-viewer-card__estado">{{ botella.estado ?? 'SIN ESTADO' }}</span>
      <span :class="['botella-viewer-card__origen', `is-${botella.origen}`]">
        {{ botella.origen === 'legado' ? 'Legado' : 'Cromo' }}
      </span>
      <i class="ph ph-arrow-up-right botella-viewer-card__arrow" aria-hidden="true"></i>
    </div>

    <h3 class="botella-viewer-card__name">{{ botella.nombre || `Botella ${botella.id}` }}</h3>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { useRouter } from 'vue-router';

import { estadoBotellaToken, type BotellaUnificadaItem } from '../../api/botellas';
import { botellaDetailPath } from '../../utils/botellaLinks';

const props = defineProps<{
  botella: BotellaUnificadaItem;
}>();

const router = useRouter();
const estadoToken = computed(() => estadoBotellaToken(props.botella.estado));

function goToDetail(): void {
  void router.push(botellaDetailPath(props.botella.origen, props.botella.id));
}
</script>

<style scoped>
.botella-viewer-card {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 12px 13px 11px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  overflow: hidden;
  transition: box-shadow 0.15s ease;
}

.botella-viewer-card:hover,
.botella-viewer-card:focus-visible {
  box-shadow: 0 0 0 1px var(--color-accent), 0 6px 18px rgba(0, 0, 0, 0.5);
}

.botella-viewer-card__row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.botella-viewer-card__dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.botella-viewer-card__dot.is-ok { background: var(--color-state-ok); }
.botella-viewer-card__dot.is-warn { background: var(--color-state-warn); }
.botella-viewer-card__dot.is-error { background: var(--color-state-error); }
.botella-viewer-card__dot.is-idle { background: var(--color-state-idle); }

.botella-viewer-card__estado {
  font-size: 10px;
  letter-spacing: 0.08em;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.botella-viewer-card__origen {
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  letter-spacing: 0.04em;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.botella-viewer-card__origen.is-cromo {
  background: color-mix(in srgb, var(--color-accent) 16%, transparent);
  color: var(--color-accent-200);
}

.botella-viewer-card__arrow {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-neutral-600);
}

.botella-viewer-card__name {
  margin: 0;
  min-height: 36px;
  font-size: 14.5px;
  font-weight: 500;
  line-height: 1.25;
  letter-spacing: -0.005em;
  text-wrap: pretty;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
