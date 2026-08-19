<!--
  Nombre de archivo: BotellaCard.vue
  Ubicación de archivo: web/frontend/src/components/infra/BotellaCard.vue
  Descripción: Tarjeta mínima de Botella (origen, ID, nombre, estado) para el visor unificado con scroll infinito
-->
<template>
  <article
    class="botella-card-min"
    :class="{ 'is-selected': selected }"
    role="button"
    tabindex="0"
    @click="goToDetail"
    @keyup.enter="goToDetail"
  >
    <div class="botella-card-min__row">
      <input
        type="checkbox"
        class="botella-card-min__checkbox"
        :checked="selected"
        @click.stop
        @change="$emit('toggleSelect', botella)"
      />
      <span :class="['botella-card-min__origen', `is-${botella.origen}`]">
        {{ botella.origen === 'cromo' ? 'Cromo' : 'Legado' }}
      </span>
      <span v-if="botella.estado" :class="['botella-card-min__dot', `is-${estadoToken}`]" :title="botella.estado ?? ''" aria-hidden="true"></span>
      <i class="ph ph-arrow-up-right botella-card-min__arrow" aria-hidden="true"></i>
    </div>

    <h3 class="botella-card-min__name">{{ botella.nombre || `Botella ${botella.id}` }}</h3>

    <div class="botella-card-min__hairline"></div>

    <div class="botella-card-min__row">
      <span class="botella-card-min__id">ID {{ botella.id }}</span>
      <span v-if="botella.estado" class="botella-card-min__estado">{{ botella.estado }}</span>
      <span v-else class="botella-card-min__estado is-muted">Sin estado operativo</span>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { estadoBotellaToken, type BotellaUnificadaItem } from '../../api/botellas';

const props = defineProps<{
  botella: BotellaUnificadaItem;
  selected?: boolean;
}>();

const emit = defineEmits<{
  openDetail: [botella: BotellaUnificadaItem];
  toggleSelect: [botella: BotellaUnificadaItem];
}>();

const estadoToken = computed(() => estadoBotellaToken(props.botella.estado));

function goToDetail(): void {
  emit('openDetail', props.botella);
}
</script>

<style scoped>
.botella-card-min {
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

.botella-card-min:hover,
.botella-card-min:focus-visible {
  box-shadow: 0 0 0 1px var(--color-accent), 0 6px 18px rgba(0, 0, 0, 0.5);
}

.botella-card-min.is-selected {
  box-shadow: 0 0 0 2px var(--color-accent);
}

.botella-card-min__row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.botella-card-min__checkbox {
  flex: none;
  accent-color: var(--color-accent);
}

.botella-card-min__origen {
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  letter-spacing: 0.08em;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.botella-card-min__origen.is-cromo {
  background: color-mix(in srgb, var(--color-accent) 18%, transparent);
  color: var(--color-accent-200);
}

.botella-card-min__origen.is-legado {
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.botella-card-min__dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.botella-card-min__dot.is-ok { background: var(--color-state-ok); }
.botella-card-min__dot.is-warn { background: var(--color-state-warn); }
.botella-card-min__dot.is-error { background: var(--color-state-error); }
.botella-card-min__dot.is-idle { background: var(--color-state-idle); }

.botella-card-min__arrow {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-neutral-600);
}

.botella-card-min__name {
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

.botella-card-min__hairline {
  height: 1px;
  background: var(--color-divider);
}

.botella-card-min__id {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.botella-card-min__estado {
  margin-left: auto;
  flex: none;
  padding: 3px 9px;
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  font-family: var(--font-heading);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.03em;
  color: var(--color-accent);
}

.botella-card-min__estado.is-muted {
  border-color: var(--color-divider);
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}
</style>
