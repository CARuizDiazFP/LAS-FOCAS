<!--
  Nombre de archivo: ServicioCard.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ServicioCard.vue
  Descripción: Tarjeta de visualización para un servicio SLA en el visor con scroll infinito
-->
<template>
  <article
    class="servicio-card"
    role="button"
    tabindex="0"
    @click="goToDetail"
    @keyup.enter="goToDetail"
  >
    <header class="servicio-card__header">
      <h3>{{ servicio.numero_primer_servicio }}</h3>
      <span class="servicio-card__estado">{{ servicio.estado_servicio }}</span>
    </header>

    <dl class="servicio-card__grid">
      <div>
        <dt>Cliente</dt>
        <dd>{{ servicio.nombre_cliente || 'Sin dato' }}</dd>
      </div>
      <div>
        <dt>Línea</dt>
        <dd>{{ servicio.numero_linea || 'Sin dato' }}</dd>
      </div>
      <div>
        <dt>Tipo</dt>
        <dd>{{ servicio.tipo_servicio || 'Sin dato' }}</dd>
      </div>
      <div>
        <dt>SLA</dt>
        <dd>{{ servicio.sla_prometido || 'Sin dato' }}</dd>
      </div>
      <div class="servicio-card__direccion">
        <dt>Domicilio</dt>
        <dd>{{ domicilio }}</dd>
      </div>
    </dl>

    <section class="servicio-card__footer">
      <p class="servicio-card__history">Histórico ID: {{ historicoVisual }}</p>
      <button class="servicio-card__cta" type="button" @click.stop="goToDetail">
        {{ ctaLabel }}
      </button>
    </section>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { ServicioItem } from '../../api/servicios';

const props = defineProps<{
  servicio: ServicioItem;
}>();

const emit = defineEmits<{
  openDetail: [idOrigen: string];
}>();

const domicilio = computed(() => {
  const parts = [props.servicio.direccion, props.servicio.direccion_2, props.servicio.localidad, props.servicio.provincia]
    .map((value) => (value ?? '').trim())
    .filter((value) => value.length > 0);
  return parts.length > 0 ? parts.join(' · ') : 'Sin dato';
});

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
    return idOrigen.value || 'Sin dato';
  }
  return `${idOrigen.value} -> ${idUltimaLinea.value}`;
});

function goToDetail(): void {
  if (!idOrigen.value) return;
  emit('openDetail', idOrigen.value);
}
</script>

<style scoped>
.servicio-card {
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-lg);
  background: linear-gradient(160deg, rgba(10, 15, 23, 0.95), rgba(18, 25, 36, 0.92));
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  padding: var(--space-4);
  display: grid;
  gap: var(--space-3);
  cursor: pointer;
}

.servicio-card__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}

.servicio-card__header h3 {
  font-size: 0.98rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  margin: 0;
}

.servicio-card__estado {
  border: 1px solid rgba(63, 185, 80, 0.4);
  background: rgba(63, 185, 80, 0.12);
  border-radius: var(--radius-pill);
  padding: 2px 10px;
  font-size: 0.74rem;
  color: #9fe0ac;
  white-space: nowrap;
}

.servicio-card__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
  margin: 0;
}

.servicio-card__grid dt {
  color: var(--color-text-muted);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 2px;
}

.servicio-card__grid dd {
  margin: 0;
  color: var(--color-text-primary);
  font-size: 0.88rem;
  word-break: break-word;
}

.servicio-card__direccion {
  grid-column: 1 / -1;
}

.servicio-card__footer {
  border: 1px dashed rgba(116, 148, 190, 0.38);
  border-radius: var(--radius-md);
  background: rgba(30, 41, 59, 0.45);
  padding: var(--space-2);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.servicio-card__history {
  margin: 0;
  color: var(--color-text-muted);
  font-size: 0.78rem;
}

.servicio-card__cta {
  border: 1px solid rgba(79, 156, 255, 0.48);
  background: rgba(45, 102, 255, 0.2);
  color: #dbeafe;
  border-radius: var(--radius-sm);
  min-height: 36px;
  padding: 0 12px;
  font-weight: 600;
  cursor: pointer;
}

.servicio-card__cta:hover {
  background: rgba(45, 102, 255, 0.3);
}

@media (max-width: 720px) {
  .servicio-card__grid {
    grid-template-columns: 1fr;
  }

  .servicio-card__footer {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
