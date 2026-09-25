<!--
  Nombre de archivo: ServicioSeccionCard.vue
  Ubicación de archivo: web/frontend/src/components/servicios/detalle/ServicioSeccionCard.vue
  Descripción: Tarjeta compacta de una sección del Servicio — resume en una línea y abre la vista
  dedicada con el detalle completo
-->
<template>
  <article class="sc">
    <header class="sc__head">
      <i :class="['ph', icono, 'sc__icono']" aria-hidden="true"></i>
      <h3 class="sc__titulo">{{ titulo }}</h3>
      <span v-if="badge" class="sc__badge" :class="badgeToken ? `is-${badgeToken}` : 'is-idle'">
        {{ badge }}
      </span>
    </header>

    <div class="sc__cuerpo">
      <!-- El resumen es lo único que se ve sin navegar: todo lo demás vive en la vista dedicada,
           que es lo que mantiene esta ficha compacta. -->
      <slot>
        <p v-if="cargando" class="sc__nota">Cargando…</p>
        <p v-else-if="error" class="sc__nota is-error">{{ error }}</p>
        <p v-else class="sc__nota">{{ resumen || 'Sin datos' }}</p>
      </slot>
    </div>

    <RouterLink class="sc__link" :to="to">
      {{ accion }}
      <i class="ph ph-arrow-right" aria-hidden="true"></i>
    </RouterLink>
  </article>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router';

withDefaults(
  defineProps<{
    titulo: string;
    icono: string;
    to: string;
    accion?: string;
    resumen?: string;
    badge?: string | number | null;
    /** `ok` | `warn` | `error` | `idle`, para el color del badge. */
    badgeToken?: string | null;
    cargando?: boolean;
    error?: string;
  }>(),
  { accion: 'Ver detalle' },
);
</script>

<style scoped>
.sc {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px 10px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
  min-width: 0;
}

.sc__head {
  display: flex;
  align-items: center;
  gap: 7px;
}

.sc__icono {
  font-size: 15px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.sc__titulo {
  margin: 0;
  font-size: 12.5px;
  font-weight: var(--font-heading-weight);
  flex: 1;
  min-width: 0;
}

.sc__badge {
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.sc__badge.is-ok {
  background: color-mix(in srgb, var(--color-state-ok) 18%, transparent);
  color: var(--color-state-ok);
}

.sc__badge.is-warn {
  background: color-mix(in srgb, var(--color-state-warn) 18%, transparent);
  color: var(--color-state-warn);
}

.sc__badge.is-error {
  background: color-mix(in srgb, var(--color-state-error) 18%, transparent);
  color: var(--color-state-error);
}

.sc__badge.is-idle {
  background: color-mix(in srgb, var(--color-text) 10%, transparent);
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}

.sc__cuerpo {
  flex: 1;
  min-width: 0;
}

.sc__nota {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.45;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}

.sc__nota.is-error {
  color: var(--color-state-error);
}

.sc__link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  align-self: flex-start;
  font-size: 11.5px;
  color: var(--color-accent);
  text-decoration: none;
}

.sc__link:hover {
  text-decoration: underline;
}
</style>
