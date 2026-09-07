<!--
  Nombre de archivo: ServicioCard.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ServicioCard.vue
  Descripción: Tarjeta mínima de servicio (estado, tipo, cliente, histórico) para el visor con scroll infinito
-->
<template>
  <article
    class="servicio-card"
    :class="{ 'is-selected': selected }"
    role="button"
    tabindex="0"
    @click="goToDetail"
    @keyup.enter="goToDetail"
  >
    <div class="servicio-card__row">
      <input
        type="checkbox"
        class="servicio-card__checkbox"
        :checked="selected"
        @click.stop
        @change="$emit('toggleSelect', servicio)"
      />
      <span :class="['servicio-card__dot', `is-${estadoToken}`]" :title="servicio.estado_servicio" aria-hidden="true"></span>
      <span class="servicio-card__type">{{ tipoLabel }}</span>
      <span class="servicio-card__categoria">{{ categoriaLabel(servicio.categoria) }}</span>
      <span v-if="!servicio.es_verificable" class="servicio-card__badge-no-verificable">No verificable</span>
      <i class="ph ph-arrow-up-right servicio-card__arrow" aria-hidden="true"></i>
    </div>

    <h3 :class="['servicio-card__name', { 'is-baja': estadoToken === 'error' }]">{{ servicio.nombre_cliente || 'Cliente sin dato' }}</h3>

    <div class="servicio-card__hairline"></div>

    <div class="servicio-card__row">
      <span class="servicio-card__historico">{{ historicoVisual }}</span>
      <span class="servicio-card__tag">{{ ctaLabel }}</span>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { categoriaLabel, estadoServicioToken, type ServicioItem } from '../../api/servicios';

const props = defineProps<{
  servicio: ServicioItem;
  selected?: boolean;
}>();

const emit = defineEmits<{
  openDetail: [idOrigen: string];
  toggleSelect: [servicio: ServicioItem];
}>();

const idOrigen = computed(() => (props.servicio.numero_primer_servicio ?? '').trim());
const idUltimaLinea = computed(() => {
  const linea = (props.servicio.numero_linea ?? '').trim();
  return linea || idOrigen.value;
});

const tipoLabel = computed(() => {
  const tipo = (props.servicio.tipo_servicio ?? '').trim();
  return tipo.length > 0 ? tipo.toUpperCase() : 'SERVICIO';
});

const ctaLabel = computed(() => `${tipoLabel.value} ${idUltimaLinea.value}`);

const historicoVisual = computed(() => {
  if (!idOrigen.value || !idUltimaLinea.value || idOrigen.value === idUltimaLinea.value) {
    return `Hist. ${idOrigen.value || 'sin dato'}`;
  }
  return `${idOrigen.value} → ${idUltimaLinea.value}`;
});

const estadoToken = computed(() => estadoServicioToken(props.servicio.estado_servicio));

function goToDetail(): void {
  if (!idOrigen.value) return;
  emit('openDetail', idOrigen.value);
}
</script>

<style scoped>
.servicio-card {
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

.servicio-card:hover,
.servicio-card:focus-visible {
  box-shadow: 0 0 0 1px var(--color-accent), 0 6px 18px rgba(0, 0, 0, 0.5);
}

.servicio-card.is-selected {
  box-shadow: 0 0 0 2px var(--color-accent);
}

.servicio-card__row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.servicio-card__checkbox {
  flex: none;
  accent-color: var(--color-accent);
}

.servicio-card__categoria {
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.04em;
  background: color-mix(in srgb, var(--color-accent) 14%, transparent);
  color: var(--color-accent-200);
}

.servicio-card__dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.servicio-card__dot.is-ok { background: var(--color-state-ok); }
.servicio-card__dot.is-warn { background: var(--color-state-warn); }
.servicio-card__dot.is-error { background: var(--color-state-error); }
.servicio-card__dot.is-idle { background: var(--color-state-idle); }

.servicio-card__type {
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 10px;
  letter-spacing: 0.08em;
  background: var(--color-neutral-800);
  color: var(--color-neutral-100);
}

.servicio-card__arrow {
  margin-left: auto;
  font-size: 13px;
  color: var(--color-neutral-600);
}

.servicio-card__name {
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

.servicio-card__name.is-baja {
  color: var(--color-state-error);
}

.servicio-card__badge-no-verificable {
  padding: 2px 7px;
  border-radius: 5px;
  font-size: 9.5px;
  border: 1px solid var(--color-state-warn);
  color: var(--color-state-warn);
}

.servicio-card__hairline {
  height: 1px;
  background: var(--color-divider);
}

.servicio-card__historico {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.servicio-card__tag {
  margin-left: auto;
  flex: none;
  padding: 3px 9px;
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  font-family: var(--font-heading);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.03em;
  font-variant-numeric: tabular-nums;
  color: var(--color-accent);
}
</style>
