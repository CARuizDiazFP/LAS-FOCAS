<!--
  Nombre de archivo: ServicioSinOdfCard.vue
  Ubicación de archivo: web/frontend/src/components/infra/ServicioSinOdfCard.vue
  Descripción: Tarjeta de un Servicio Activo sin ODF resuelta — categoría/causa, ambos extremos de última milla (el que ganó la categorización marcado) y botón para abrir el modal de asociación
-->
<template>
  <article class="servicio-sin-odf-card">
    <div class="servicio-sin-odf-card__row">
      <span :class="['servicio-sin-odf-card__dot', `is-${categoriaToken}`]" aria-hidden="true"></span>
      <span class="servicio-sin-odf-card__categoria">{{ categoriaLabel }}</span>
    </div>

    <h3 class="servicio-sin-odf-card__servicio">{{ servicio.servicio_id }}</h3>
    <p class="servicio-sin-odf-card__cliente">{{ servicio.nombre_cliente || 'Sin nombre de cliente' }}</p>

    <div class="servicio-sin-odf-card__hairline"></div>

    <div v-if="servicio.extremos.length > 0" class="servicio-sin-odf-card__extremos">
      <div
        v-for="(extremo, index) in servicio.extremos"
        :key="`${extremo.extremo ?? index}`"
        :class="['servicio-sin-odf-card__extremo', { 'is-ganador': index === servicio.indice_extremo_categorizado }]"
      >
        <span class="servicio-sin-odf-card__extremo-label">
          Extremo {{ extremo.extremo ?? index + 1 }}
          <i
            v-if="index === servicio.indice_extremo_categorizado"
            class="ph ph-check-circle servicio-sin-odf-card__extremo-icon"
            title="Extremo que determinó la categoría"
            aria-hidden="true"
          ></i>
        </span>
        <span class="servicio-sin-odf-card__extremo-valor">{{ extremo.nodo || '—' }} / {{ extremo.equipo || '—' }}</span>
      </div>
    </div>
    <p v-else class="servicio-sin-odf-card__sin-extremos">Sin fila de última milla PROV.</p>

    <button class="btn primary servicio-sin-odf-card__accion" type="button" @click="$emit('asociar', servicio)">
      <i class="ph ph-link" aria-hidden="true"></i>
      Asociar ODF
    </button>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue';

import {
  categoriaServicioLabel,
  categoriaServicioToken,
  type ServicioSinOdfItem,
} from '../../api/serviciosOdf';

const props = defineProps<{
  servicio: ServicioSinOdfItem;
}>();

defineEmits<{
  asociar: [servicio: ServicioSinOdfItem];
}>();

const categoriaLabel = computed(() => categoriaServicioLabel(props.servicio.categoria_causa));
const categoriaToken = computed(() => categoriaServicioToken(props.servicio.categoria_causa));
</script>

<style scoped>
.servicio-sin-odf-card {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 12px 13px 11px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.servicio-sin-odf-card__row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.servicio-sin-odf-card__dot {
  width: 6px;
  height: 6px;
  flex: none;
  border-radius: 50%;
  background: var(--color-state-idle);
}

.servicio-sin-odf-card__dot.is-ok { background: var(--color-state-ok); }
.servicio-sin-odf-card__dot.is-warn { background: var(--color-state-warn); }
.servicio-sin-odf-card__dot.is-error { background: var(--color-state-error); }
.servicio-sin-odf-card__dot.is-idle { background: var(--color-state-idle); }

.servicio-sin-odf-card__categoria {
  font-size: 10px;
  letter-spacing: 0.06em;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.servicio-sin-odf-card__servicio {
  margin: 0;
  font-size: 14.5px;
  font-weight: 500;
  letter-spacing: -0.005em;
}

.servicio-sin-odf-card__cliente {
  margin: 0;
  font-size: 12px;
  line-height: 1.3;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.servicio-sin-odf-card__hairline {
  height: 1px;
  background: var(--color-divider);
}

.servicio-sin-odf-card__extremos {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.servicio-sin-odf-card__extremo {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 5px 7px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-text) 4%, transparent);
}

.servicio-sin-odf-card__extremo.is-ganador {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
}

.servicio-sin-odf-card__extremo-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 9.5px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.servicio-sin-odf-card__extremo-icon {
  font-size: 11px;
  color: var(--color-accent);
}

.servicio-sin-odf-card__extremo-valor {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.servicio-sin-odf-card__sin-extremos {
  margin: 0;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.servicio-sin-odf-card__accion {
  margin-top: 2px;
  padding: 6px 10px;
  font-size: 12px;
  align-self: flex-start;
}
</style>
