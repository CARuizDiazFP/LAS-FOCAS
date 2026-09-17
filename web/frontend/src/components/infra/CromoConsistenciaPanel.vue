<!--
  Nombre de archivo: CromoConsistenciaPanel.vue
  Ubicación de archivo: web/frontend/src/components/infra/CromoConsistenciaPanel.vue
  Descripción: Compara lo que declara el camino de Cromo contra lo ingerido, sin acusar a la base: el camino es un elemento vivo
-->
<template>
  <section class="cromo-consistencia">
    <header class="cromo-consistencia__head">
      <h4 class="cromo-consistencia__titulo">Consistencia con lo ingerido</h4>
      <span class="cromo-consistencia__resumen" :class="tokenResumen">
        <template v-if="consistencia.total_discrepa === 0 && consistencia.total_no_ingerido === 0">
          Todo coincide
        </template>
        <template v-else>
          {{ consistencia.total_discrepa }} difieren ·
          {{ consistencia.total_no_ingerido }} sin ingerir
        </template>
      </span>
    </header>

    <!-- Redacción deliberada: el camino DIFIERE de lo ingerido, no "la base está mal". El camino
         cambia ante cortes y la ingesta es una foto anterior, así que una diferencia puede ser
         deriva legítima. En los dos casos la referencia es Cromo. -->
    <p class="cromo-consistencia__nota">
      Compara las relaciones que declara el camino contra las que tenemos ingeridas. Una diferencia
      puede ser deriva legítima —el camino cambia ante cortes y la ingesta es una foto anterior— y
      en cualquier caso <strong>Cromo es la referencia</strong>.
    </p>

    <table class="cromo-consistencia__tabla">
      <thead>
        <tr>
          <th scope="col">Relación</th>
          <th scope="col">Coincide</th>
          <th scope="col">Difiere</th>
          <th scope="col">Sin ingerir</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="regla in consistencia.reglas" :key="regla.regla">
          <th scope="row" class="cromo-consistencia__regla">{{ regla.descripcion }}</th>
          <td>{{ regla.coincide }}<span class="cromo-consistencia__total">/{{ regla.total }}</span></td>
          <td :class="{ 'is-error': regla.discrepa > 0 }">{{ regla.discrepa }}</td>
          <td :class="{ 'is-idle': regla.no_ingerido > 0 }">{{ regla.no_ingerido }}</td>
        </tr>
      </tbody>
    </table>

    <!-- La acción que faltaba: hasta ahora la tabla sólo informaba. Normalizar vuelve a traer de
         Cromo el objeto real y lo reingiere, que es lo que significa "Cromo es la referencia". -->
    <div v-if="mostrarAcciones" class="cromo-consistencia__acciones">
      <button
        type="button"
        class="btn subtle"
        :disabled="normalizando"
        :title="
          'Reingiere desde Cromo los ' +
          consistencia.inconsistencias.length +
          ' elementos inconsistentes. Cuesta una llamada a Cromo por elemento.'
        "
        @click="$emit('normalizar', null)"
      >
        {{ normalizando ? 'Normalizando…' : `Normalizar los ${consistencia.inconsistencias.length} casos` }}
      </button>
      <span v-if="resumen" class="cromo-consistencia__resultado">{{ resumen }}</span>
      <span v-if="error" class="cromo-consistencia__resultado is-error">{{ error }}</span>
    </div>

    <details v-if="consistencia.inconsistencias.length > 0" class="cromo-consistencia__detalle">
      <summary>Ver los {{ consistencia.inconsistencias.length }} casos</summary>
      <ul class="cromo-consistencia__lista">
        <li
          v-for="(caso, indice) in consistencia.inconsistencias"
          :key="`${caso.regla}-${caso.elemento_id}-${indice}`"
          class="cromo-consistencia__caso"
          :class="caso.tipo === 'DISCREPA' ? 'is-error' : 'is-idle'"
        >
          <span class="cromo-consistencia__caso-tipo">
            {{ caso.tipo === 'DISCREPA' ? 'Difiere' : 'Sin ingerir' }}
          </span>
          <span class="cromo-consistencia__caso-cuerpo">
            <strong>{{ caso.regla }}</strong> · elemento {{ caso.elemento_id }}
            <template v-if="caso.tipo === 'DISCREPA'">
              — el camino dice {{ formatear(caso.valor_path) }}, la base dice
              {{ formatear(caso.valor_local) }}
            </template>
            <template v-else>
              — el camino lo declara ({{ formatear(caso.valor_path) }}) y no está en la base
            </template>
          </span>
          <button
            v-if="mostrarAcciones"
            type="button"
            class="cromo-consistencia__caso-accion"
            :disabled="normalizando"
            title="Reingiere sólo este elemento desde Cromo"
            @click="$emit('normalizar', [caso.elemento_id])"
          >
            Normalizar
          </button>
        </li>
      </ul>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue';

import type { ConsistenciaCamino } from '../../api/cromoPath';

const props = defineProps<{
  consistencia: ConsistenciaCamino;
  /** Escribir inventario es admin: sin permiso el panel sigue informando, pero sin acciones. */
  puedeNormalizar?: boolean;
  normalizando?: boolean;
  resumen?: string;
  error?: string;
}>();

defineEmits<{
  /** `null` = normalizar todo lo inconsistente; una lista = sólo esos elementos. */
  normalizar: [elementoIds: number[] | null];
}>();

/** Sin casos que corregir no hay nada que normalizar: el botón sería ruido. */
const mostrarAcciones = computed(
  () => props.puedeNormalizar === true && props.consistencia.inconsistencias.length > 0,
);

const tokenResumen = computed(() => {
  if (props.consistencia.total_discrepa > 0) {
    return 'is-error';
  }
  if (props.consistencia.total_no_ingerido > 0) {
    return 'is-idle';
  }
  return 'is-ok';
});

function formatear(valor: unknown): string {
  if (valor === null || valor === undefined) {
    return '—';
  }
  if (Array.isArray(valor)) {
    return valor.join(', ');
  }
  if (typeof valor === 'object') {
    return Object.entries(valor as Record<string, unknown>)
      .map(([clave, item]) => `${clave}=${item ?? '—'}`)
      .join(' ');
  }
  return String(valor);
}
</script>

<style scoped>
.cromo-consistencia {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 9px 10px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-text) 4%, transparent);
}

.cromo-consistencia__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.cromo-consistencia__titulo {
  margin: 0;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.cromo-consistencia__resumen {
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  font-size: 10px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.cromo-consistencia__resumen.is-ok {
  background: color-mix(in srgb, var(--color-state-ok) 18%, transparent);
  color: var(--color-state-ok);
}

.cromo-consistencia__resumen.is-error {
  background: color-mix(in srgb, var(--color-state-error) 18%, transparent);
  color: var(--color-state-error);
}

.cromo-consistencia__resumen.is-idle {
  background: color-mix(in srgb, var(--color-state-idle) 18%, transparent);
  color: var(--color-state-idle);
}

.cromo-consistencia__nota {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.cromo-consistencia__tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}

.cromo-consistencia__tabla th,
.cromo-consistencia__tabla td {
  padding: 4px 5px;
  text-align: right;
  border-bottom: 1px solid var(--color-divider);
}

.cromo-consistencia__tabla thead th {
  font-size: 9.5px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  font-weight: 400;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.cromo-consistencia__regla {
  text-align: left;
  font-weight: 400;
  color: color-mix(in srgb, var(--color-text) 75%, transparent);
}

.cromo-consistencia__total {
  color: color-mix(in srgb, var(--color-text) 40%, transparent);
}

.cromo-consistencia__tabla td.is-error {
  color: var(--color-state-error);
}

.cromo-consistencia__tabla td.is-idle {
  color: var(--color-state-idle);
}

.cromo-consistencia__detalle {
  font-size: 11.5px;
}

.cromo-consistencia__detalle summary {
  cursor: pointer;
  color: var(--color-accent);
}

.cromo-consistencia__lista {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  max-height: 180px;
  overflow-y: auto;
}

.cromo-consistencia__caso {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  background: var(--color-surface);
}

.cromo-consistencia__caso-tipo {
  flex: none;
  padding: 0 5px;
  border-radius: var(--radius-pill);
  font-size: 9px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.cromo-consistencia__caso.is-error .cromo-consistencia__caso-tipo {
  background: color-mix(in srgb, var(--color-state-error) 18%, transparent);
  color: var(--color-state-error);
}

.cromo-consistencia__caso.is-idle .cromo-consistencia__caso-tipo {
  background: color-mix(in srgb, var(--color-state-idle) 18%, transparent);
  color: var(--color-state-idle);
}

.cromo-consistencia__caso-cuerpo {
  min-width: 0;
  line-height: 1.4;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.cromo-consistencia__acciones {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.cromo-consistencia__resultado {
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 65%, transparent);
}

.cromo-consistencia__resultado.is-error {
  color: var(--color-state-error);
}

.cromo-consistencia__caso-accion {
  flex-shrink: 0;
  align-self: center;
  padding: 2px 8px;
  border: 0;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-text) 8%, transparent);
  color: color-mix(in srgb, var(--color-text) 75%, transparent);
  font-size: 10.5px;
  cursor: pointer;
}

.cromo-consistencia__caso-accion:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-accent) 22%, transparent);
  color: var(--color-text);
}

.cromo-consistencia__caso-accion:disabled {
  opacity: 0.45;
  cursor: default;
}
</style>
