<!--
  Nombre de archivo: CromoPeloSelector.vue
  Ubicación de archivo: web/frontend/src/components/infra/CromoPeloSelector.vue
  Descripción: Selector de pelos de un Servicio — tilda cuáles se descargan (varios) y cuál se
  dibuja en pantalla (uno solo, porque resolver el camino cuesta una llamada a Cromo por pelo)
-->
<template>
  <!-- Con una sola semilla no hay nada que elegir: una lista de un elemento es ruido, así que se
       informa cuál se va a usar en una oración. -->
  <p v-if="pelos.length === 1" class="cromo-pelo-selector__unico">
    Se resolverá desde el pelo
    <strong>{{ pelos[0].numero_pelo ?? pelos[0].pelo_n_id }}</strong>
    <span v-if="pelos[0].color"> ({{ pelos[0].color }})</span>
    <span v-if="pelos[0].cable_nombre"> del cable {{ pelos[0].cable_nombre }}</span>
    · n_id {{ pelos[0].pelo_n_id }}
  </p>

  <fieldset v-else-if="pelos.length > 1" class="cromo-pelo-selector">
    <legend class="cromo-pelo-selector__legend">
      <template v-if="posiciones.length">
        {{ posiciones.length }} posición(es) de ODF del Servicio — tildá cuáles descargar
      </template>
      <template v-else>{{ pelos.length }} pelos de Cromo — tildá cuáles descargar</template>
    </legend>

    <!-- El número de servicio viaja en el at.61 de TODOS los pelos del recorrido, no sólo de los
         extremos: por eso el total matcheado es grande y no es "la cantidad de pelos del
         Servicio". Decirlo evita que el operador crea que le faltan o le sobran fibras. -->
    <p v-if="totalMatcheados > pelos.length" class="cromo-pelo-selector__universo">
      {{ totalMatcheados }} pelos del recorrido llevan la etiqueta de este Servicio; se listan
      {{ pelos.length }}.
    </p>

    <!-- Un Servicio tiene un tracking por pelo, así que la selección de descarga es múltiple. -->
    <div class="cromo-pelo-selector__acciones">
      <span class="cromo-pelo-selector__conteo">
        {{ seleccionados.length }} de {{ principales.length }} tildados
      </span>
      <button
        type="button"
        class="cromo-pelo-selector__accion"
        :disabled="disabled || seleccionados.length === pelos.length"
        @click="$emit('seleccionar-todos')"
      >
        Todos
      </button>
      <button
        type="button"
        class="cromo-pelo-selector__accion"
        :disabled="disabled || seleccionados.length === 0"
        @click="$emit('limpiar-seleccion')"
      >
        Ninguno
      </button>
    </div>

    <div
      v-for="pelo in principales"
      :key="pelo.pelo_n_id"
      class="cromo-pelo-selector__opcion"
      :class="{ 'is-elegido': pelo.pelo_n_id === modelValue }"
    >
      <label class="cromo-pelo-selector__tilde">
        <input
          type="checkbox"
          :checked="seleccionados.includes(pelo.pelo_n_id)"
          :disabled="disabled"
          @change="$emit('alternar', pelo.pelo_n_id)"
        />
        <span class="cromo-pelo-selector__sr">Descargar el tracking del pelo {{ pelo.pelo_n_id }}</span>
      </label>

      <span class="cromo-pelo-selector__cuerpo">
        <span class="cromo-pelo-selector__titulo">
          Pelo {{ pelo.numero_pelo ?? '—' }}
          <span v-if="pelo.color" class="cromo-pelo-selector__color">{{ pelo.color }}</span>
          <span v-if="pelo.cable_nombre" class="cromo-pelo-selector__cable">
            · {{ pelo.cable_nombre }}
          </span>
          <!-- Es una posición de patchera real del Servicio: el tracking que el operador quiere. -->
          <span v-if="pelo.tiene_conector_odf" class="cromo-pelo-selector__chip is-ok">
            Posición de ODF
          </span>
          <!-- Sin caché, cada pelo cuesta entre 4,6 s y 14 s contra Cromo. -->
          <span
            v-if="pelo.tracking_en_cache"
            class="cromo-pelo-selector__chip is-cache"
            :title="`Tracking generado el ${formatearFecha(pelo.tracking_en_cache)}`"
          >
            En caché
          </span>
        </span>
        <span class="cromo-pelo-selector__meta">
          n_id {{ pelo.pelo_n_id }}
          <template v-if="pelo.metodo"> · {{ pelo.metodo }}</template>
          <template v-if="pelo.confianza !== null"> · confianza {{ pelo.confianza }}</template>
        </span>
        <!-- `at.61` crudo: es el "por qué matcheó". Con el 96,6% de los pelos sin número
             extraído, ver el texto original es lo que le permite al operador evaluar la semilla. -->
        <span v-if="pelo.servicio_raw" class="cromo-pelo-selector__raw" :title="pelo.servicio_raw">
          {{ pelo.servicio_raw }}
        </span>
      </span>

      <!-- Dibujar el camino es lo caro (una llamada a Cromo por pelo), así que sigue siendo de a
           uno y por acción explícita, separado de la descarga. -->
      <span v-if="pelo.pelo_n_id === modelValue" class="cromo-pelo-selector__chip is-activo">
        En pantalla
      </span>
      <button
        v-else
        type="button"
        class="cromo-pelo-selector__accion"
        :disabled="disabled"
        @click="$emit('update:modelValue', pelo.pelo_n_id)"
      >
        Ver camino
      </button>
    </div>

    <!-- Los pelos del recorrido que no son posición de ODF siguen disponibles —sirven para
         resolver el camino desde otra semilla— pero colapsados: mostrarlos al mismo nivel haría
         parecer que el Servicio tiene veinte fibras cuando tiene dos. -->
    <details v-if="resto.length" class="cromo-pelo-selector__resto">
      <summary>Ver los otros {{ resto.length }} pelos del recorrido</summary>
      <div
        v-for="pelo in resto"
        :key="pelo.pelo_n_id"
        class="cromo-pelo-selector__opcion"
        :class="{ 'is-elegido': pelo.pelo_n_id === modelValue }"
      >
        <label class="cromo-pelo-selector__tilde">
          <input
            type="checkbox"
            :checked="seleccionados.includes(pelo.pelo_n_id)"
            :disabled="disabled"
            @change="$emit('alternar', pelo.pelo_n_id)"
          />
          <span class="cromo-pelo-selector__sr">
            Descargar el tracking del pelo {{ pelo.pelo_n_id }}
          </span>
        </label>
        <span class="cromo-pelo-selector__cuerpo">
          <span class="cromo-pelo-selector__titulo">
            Pelo {{ pelo.numero_pelo ?? '—' }}
            <span v-if="pelo.cable_nombre" class="cromo-pelo-selector__cable">
              · {{ pelo.cable_nombre }}
            </span>
            <span
              v-if="pelo.tracking_en_cache"
              class="cromo-pelo-selector__chip is-cache"
              :title="`Tracking generado el ${formatearFecha(pelo.tracking_en_cache)}`"
            >
              En caché
            </span>
          </span>
          <span class="cromo-pelo-selector__meta">n_id {{ pelo.pelo_n_id }}</span>
        </span>
        <span v-if="pelo.pelo_n_id === modelValue" class="cromo-pelo-selector__chip is-activo">
          En pantalla
        </span>
        <button
          v-else
          type="button"
          class="cromo-pelo-selector__accion"
          :disabled="disabled"
          @click="$emit('update:modelValue', pelo.pelo_n_id)"
        >
          Ver camino
        </button>
      </div>
    </details>
  </fieldset>
</template>

<script setup lang="ts">
import { computed } from 'vue';

import type { PeloSemilla } from '../../api/cromoPath';

const props = withDefaults(
  defineProps<{
    pelos: PeloSemilla[];
    modelValue: number | null;
    seleccionados: number[];
    disabled?: boolean;
    /** Universo real de pelos matcheados, sin el tope que trunca `pelos`. */
    totalMatcheados?: number;
  }>(),
  { totalMatcheados: 0 },
);

/**
 * Las posiciones de patchera son "los pelos del Servicio" para el operador. El resto son los pelos
 * del recorrido que llevan la misma etiqueta de servicio en su `at.61` — sirven para resolver el
 * camino desde otra semilla, pero no son fibras del Servicio.
 */
const posiciones = computed(() => props.pelos.filter((p) => p.tiene_conector_odf));

/** Si no hay ninguna posición de ODF (ODF sin relevar) se listan todos, que es lo único que hay. */
const principales = computed(() => (posiciones.value.length ? posiciones.value : props.pelos));
const resto = computed(() =>
  posiciones.value.length ? props.pelos.filter((p) => !p.tiene_conector_odf) : [],
);

defineEmits<{
  'update:modelValue': [pelo: number];
  alternar: [pelo: number];
  'seleccionar-todos': [];
  'limpiar-seleccion': [];
}>();

function formatearFecha(iso: string): string {
  const fecha = new Date(iso);
  return Number.isNaN(fecha.getTime()) ? iso : fecha.toLocaleString();
}
</script>

<style scoped>
.cromo-pelo-selector {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 8px 9px;
  border: 0;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-text) 4%, transparent);
}

.cromo-pelo-selector__legend {
  padding: 0 0 4px;
  font-size: 10px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.cromo-pelo-selector__unico {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: color-mix(in srgb, var(--color-text) 66%, transparent);
}

.cromo-pelo-selector__acciones {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  padding-bottom: 2px;
}

.cromo-pelo-selector__conteo {
  margin-right: auto;
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.cromo-pelo-selector__accion {
  padding: 2px 8px;
  border: 0;
  border-radius: var(--radius-pill);
  background: color-mix(in srgb, var(--color-text) 8%, transparent);
  color: color-mix(in srgb, var(--color-text) 75%, transparent);
  font-size: 10.5px;
  cursor: pointer;
}

.cromo-pelo-selector__accion:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-accent) 22%, transparent);
  color: var(--color-text);
}

.cromo-pelo-selector__accion:disabled {
  opacity: 0.45;
  cursor: default;
}

.cromo-pelo-selector__opcion {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 6px 7px;
  border-radius: var(--radius-sm);
  background: var(--color-bg);
}

.cromo-pelo-selector__opcion.is-elegido {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-accent) 45%, transparent);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
}

.cromo-pelo-selector__tilde {
  display: flex;
  align-items: center;
  padding-top: 2px;
  cursor: pointer;
}

.cromo-pelo-selector__sr {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.cromo-pelo-selector__cuerpo {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.cromo-pelo-selector__titulo {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  font-size: 12.5px;
}

.cromo-pelo-selector__color,
.cromo-pelo-selector__cable {
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.cromo-pelo-selector__chip {
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  font-size: 9.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}

.cromo-pelo-selector__chip.is-ok {
  background: color-mix(in srgb, var(--color-state-ok) 18%, transparent);
  color: var(--color-state-ok);
}

.cromo-pelo-selector__chip.is-cache {
  background: color-mix(in srgb, var(--color-text) 10%, transparent);
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.cromo-pelo-selector__chip.is-activo {
  align-self: center;
  background: color-mix(in srgb, var(--color-accent) 22%, transparent);
  color: var(--color-text);
}

.cromo-pelo-selector__meta {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.cromo-pelo-selector__raw {
  font-size: 10.5px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cromo-pelo-selector__universo {
  margin: 0 0 2px;
  font-size: 10.5px;
  line-height: 1.4;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.cromo-pelo-selector__resto {
  margin-top: 2px;
}

.cromo-pelo-selector__resto > summary {
  cursor: pointer;
  font-size: 10.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
  padding: 3px 0;
}

.cromo-pelo-selector__resto > .cromo-pelo-selector__opcion {
  margin-top: 4px;
}
</style>
