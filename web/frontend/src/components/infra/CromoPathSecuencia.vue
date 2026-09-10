<!--
  Nombre de archivo: CromoPathSecuencia.vue
  Ubicación de archivo: web/frontend/src/components/infra/CromoPathSecuencia.vue
  Descripción: Dibuja la secuencia de nodos de un camino óptico de Cromo, mostrando los huecos en vez de esconderlos
-->
<template>
  <div class="cromo-path" :style="{ maxHeight: maxAltura }">
    <p v-if="truncado" class="cromo-path__aviso is-warn">
      <i class="ph ph-warning" aria-hidden="true"></i>
      El camino vino truncado: se muestra lo que Cromo devolvió.
    </p>

    <ol class="cromo-path__lista">
      <li
        v-for="(nodo, indice) in nodos"
        :key="`${nodo.lado}-${nodo.orden}-${nodo.id_cromo}-${indice}`"
        class="cromo-path__nodo"
        :class="claseDelNodo(nodo)"
      >
        <i class="ph cromo-path__icono" :class="tipoNodoIcono(nodo.tipo)" aria-hidden="true"></i>

        <span class="cromo-path__cuerpo">
          <span class="cromo-path__titulo">
            <template v-if="nodo.tipo === 'NO_RESUELTO'">
              Elemento {{ nodo.id_cromo }} no resuelto por Cromo
            </template>
            <template v-else-if="nodo.tipo === 'CONECTOR_ODF'">
              {{ nodo.patchera_nombre ?? nodo.odf_nombre ?? 'Conector' }}
              <span v-if="nodo.conector_numero" class="cromo-path__conector">
                conector {{ nodo.conector_numero }}
              </span>
            </template>
            <template v-else-if="nodo.tipo === 'FUSION'">
              Fusión {{ nodo.nombre ?? '' }}
              <span v-if="nodo.botella_nombre" class="cromo-path__botella">
                en {{ nodo.botella_nombre }}
              </span>
            </template>
            <template v-else-if="nodo.tipo === 'PELO'">
              {{ nodo.cable_nombre ?? 'Cable s/d' }}
              <span class="cromo-path__pelo">
                pelo {{ nodo.numero_pelo ?? '—' }}
                <template v-if="nodo.tubo_color">· tubo {{ nodo.tubo_color }}</template>
              </span>
            </template>
            <template v-else>
              {{ tipoNodoLabel(nodo.tipo) }} {{ nodo.nombre ?? nodo.id_cromo }}
            </template>
          </span>

          <span class="cromo-path__meta">
            <span class="cromo-path__id">n_id {{ nodo.id_cromo }}</span>
            <template v-if="nodo.distancia_real_m !== null">
              · {{ formatearMetros(nodo.distancia_real_m) }} m
            </template>
            <!-- Un nodo sin fila local no es un error: puede ser una clase que la ingesta no
                 barre, o un objeto que Cromo movió después de la última corrida. -->
            <span v-if="!nodo.vinculo_local && nodo.tipo !== 'NO_RESUELTO'" class="cromo-path__solo-cromo">
              · sólo en Cromo
            </span>
            <span v-else-if="nodo.vinculo_local && !nodo.vinculo_local.vigente" class="cromo-path__no-vigente">
              · no vigente en la base
            </span>
            <span v-if="nodo.repetido" class="cromo-path__repetido">· repetido</span>
          </span>
        </span>

        <!-- Deep-link en pestaña nueva: en la misma se desmontaría el modal y se perdería un
             resultado que costó ~12 s de Cromo. -->
        <a
          v-if="rutaDelNodo(nodo)"
          class="cromo-path__link"
          :href="rutaDelNodo(nodo)!"
          target="_blank"
          rel="noopener"
          :title="`Abrir el detalle de ${tipoNodoLabel(nodo.tipo)}`"
        >
          <i class="ph ph-arrow-square-out" aria-hidden="true"></i>
        </a>
      </li>
    </ol>
  </div>
</template>

<script setup lang="ts">
import { type NodoCamino, tipoNodoIcono, tipoNodoLabel } from '../../api/cromoPath';

const props = defineProps<{
  nodos: NodoCamino[];
  truncado?: boolean;
  esHermano?: boolean;
  maxAltura?: string;
}>();

const maxAltura = props.maxAltura ?? '320px';

function claseDelNodo(nodo: NodoCamino): string[] {
  const clases: string[] = [];
  if (nodo.tipo === 'NO_RESUELTO') {
    clases.push('is-warn');
  } else if (!nodo.vinculo_local) {
    clases.push('is-idle');
  }
  if (props.esHermano) {
    clases.push('is-hermano');
  }
  return clases;
}

function formatearMetros(valor: number): string {
  return Number.isInteger(valor) ? String(valor) : valor.toFixed(1);
}

function rutaDelNodo(nodo: NodoCamino): string | null {
  const nId = nodo.vinculo_local?.n_id;
  if (!nId) {
    return null;
  }
  if (nodo.tipo === 'CONECTOR_ODF' && nodo.odf_id) {
    return `/infra/cromo/odfs/ID${nodo.odf_id}`;
  }
  if (nodo.tipo === 'PELO' && nodo.cable_id) {
    return `/infra/cromo/cables/ID${nodo.cable_id}`;
  }
  return null;
}
</script>

<style scoped>
.cromo-path {
  overflow-y: auto;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-text) 3%, transparent);
}

.cromo-path__aviso {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 6px 9px;
  font-size: 11.5px;
}

.cromo-path__aviso.is-warn {
  background: color-mix(in srgb, var(--color-state-warn) 16%, transparent);
  color: var(--color-state-warn);
}

.cromo-path__lista {
  display: flex;
  flex-direction: column;
  gap: 1px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.cromo-path__nodo {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 9px;
  background: var(--color-surface);
}

.cromo-path__nodo.is-warn {
  box-shadow: inset 2px 0 0 var(--color-state-warn);
}

.cromo-path__nodo.is-idle {
  box-shadow: inset 2px 0 0 var(--color-state-idle);
}

.cromo-path__nodo.is-hermano {
  background: color-mix(in srgb, var(--color-state-warn) 8%, var(--color-surface));
}

.cromo-path__icono {
  flex: none;
  margin-top: 2px;
  font-size: 13px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.cromo-path__cuerpo {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}

.cromo-path__titulo {
  font-size: 12.5px;
  line-height: 1.35;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cromo-path__conector,
.cromo-path__botella,
.cromo-path__pelo {
  color: color-mix(in srgb, var(--color-text) 58%, transparent);
}

.cromo-path__meta {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 48%, transparent);
}

.cromo-path__solo-cromo,
.cromo-path__repetido {
  color: var(--color-state-idle);
}

.cromo-path__no-vigente {
  color: var(--color-state-warn);
}

.cromo-path__link {
  flex: none;
  padding: 2px;
  color: var(--color-accent);
  font-size: 12px;
  text-decoration: none;
}
</style>
