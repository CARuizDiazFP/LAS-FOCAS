<!--
  Nombre de archivo: CromoCaminoPanel.vue
  Ubicación de archivo: web/frontend/src/components/infra/CromoCaminoPanel.vue
  Descripción: Panel reutilizable del camino óptico de Cromo — semillas, resolución cancelable, estadísticas, auditoría de consistencia y secuencia de nodos
-->
<template>
  <section class="cromo-camino">
    <header class="cromo-camino__head">
      <h4 class="cromo-camino__titulo">Camino óptico en Cromo</h4>
      <button
        v-if="camino.tieneSemilla.value"
        class="btn subtle"
        type="button"
        :disabled="camino.resolviendo.value"
        @click="servicioId != null && camino.resolver(servicioId)"
      >
        <i class="ph ph-tree-structure" aria-hidden="true"></i>
        {{ camino.resultado.value ? 'Resolver de nuevo' : 'Resolver camino' }}
      </button>
    </header>

    <p v-if="camino.cargandoPelos.value" class="cromo-camino__nota">Buscando pelos…</p>
    <p v-else-if="!camino.tieneSemilla.value" class="cromo-camino__nota">
      Este Servicio no tiene ningún pelo en Cromo, así que no hay camino que resolver.
    </p>

    <CromoPeloSelector
      v-if="camino.tieneSemilla.value"
      :pelos="camino.pelos.value"
      :model-value="camino.peloElegido.value"
      :disabled="camino.resolviendo.value"
      @update:model-value="camino.peloElegido.value = $event"
    />

    <!-- Espera honesta: sin progreso del servidor, el único progreso real es el tiempo. -->
    <div
      v-if="camino.resolviendo.value"
      class="cromo-camino__esperando"
      aria-live="polite"
      aria-busy="true"
    >
      <i class="ph ph-circle-notch cromo-camino__spin" aria-hidden="true"></i>
      <span>Resolviendo camino en Cromo… {{ camino.segundos.value }} s</span>
      <button class="btn subtle" type="button" @click="camino.cancelar()">Cancelar</button>
      <p v-if="camino.avisoLento.value" class="cromo-camino__nota">
        Cromo resuelve el grafo en memoria; un camino largo puede tardar más. Podés cancelar y
        seguir sin él: el camino es una señal, no un requisito.
      </p>
    </div>

    <p v-else-if="camino.cancelado.value" class="cromo-camino__nota">
      Cancelaste la resolución.
    </p>
    <p v-else-if="camino.errorPath.value" class="cromo-camino__error">
      {{ camino.errorPath.value }}
    </p>

    <template v-else-if="camino.resultado.value">
      <p v-if="camino.resultado.value.estado !== 'OK'" class="cromo-camino__nota">
        {{ camino.resultado.value.motivo }}
      </p>

      <template v-else>
        <p class="cromo-camino__meta">
          {{ camino.resultado.value.estadisticas.nodos }} nodos ·
          {{ camino.resultado.value.estadisticas.cables }} cables ·
          {{ camino.resultado.value.estadisticas.odfs }} ODFs ·
          {{ Math.round(camino.resultado.value.estadisticas.longitud_optica_m) }} m ópticos ·
          pelo n_id {{ camino.resultado.value.pelo_n_id }}
          <template v-if="camino.resultado.value.servicio_at62">
            · at.62 <strong>{{ camino.resultado.value.servicio_at62 }}</strong>
          </template>
          <template v-if="camino.resultado.value.duracion_ms">
            · {{ (camino.resultado.value.duracion_ms / 1000).toFixed(1) }} s
          </template>
        </p>

        <p
          v-for="(aviso, i) in camino.resultado.value.advertencias"
          :key="i"
          class="cromo-camino__aviso"
        >
          <i class="ph ph-warning" aria-hidden="true"></i> {{ aviso }}
        </p>

        <!-- ODFs descubiertas: se ofrecen, no se aplican. -->
        <ul v-if="camino.resultado.value.odfs.length > 0" class="cromo-camino__odfs">
          <li v-for="odf in camino.resultado.value.odfs" :key="odf.odf_id">
            <span class="cromo-camino__odf-nombre">
              {{ odf.nombre || `ODF ${odf.odf_id}` }}
              <span class="cromo-camino__odf-meta">
                lado {{ odf.lado }}
                <template v-if="odf.patchera_nombre"> · {{ odf.patchera_nombre }}</template>
                <template v-if="odf.conector_numero"> · conector {{ odf.conector_numero }}</template>
              </span>
            </span>
            <!-- Qué se puede HACER con una ODF descubierta depende de quién muestre el
                 camino: el modal de asociación la trae al buscador, el detalle del Servicio sólo
                 la informa. El panel no decide por ellos. -->
            <slot name="odf-accion" :odf="odf"></slot>
          </li>
        </ul>

        <CromoConsistenciaPanel
          v-if="camino.resultado.value.consistencia"
          :consistencia="camino.resultado.value.consistencia"
        />

        <CromoPathSecuencia
          :nodos="[
            ...camino.resultado.value.lado_b.slice().reverse(),
            ...(camino.resultado.value.raiz ? [camino.resultado.value.raiz] : []),
            ...camino.resultado.value.lado_a,
          ]"
          :truncado="camino.resultado.value.ids_no_resueltos.length > 0"
        />
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
// El estado vive en el PADRE, no acá: tanto el modal de asociación (que persiste el
// `pelo_n_id` del camino resuelto al confirmar) como el detalle del Servicio (que descarga el
// .txt del pelo elegido) necesitan leerlo. El panel dibuja y dispara; no es dueño de nada.
import type { OdfDelCamino } from '../../api/cromoPath';
import type { useCromoPath } from '../../composables/useCromoPath';
import CromoConsistenciaPanel from './CromoConsistenciaPanel.vue';
import CromoPathSecuencia from './CromoPathSecuencia.vue';
import CromoPeloSelector from './CromoPeloSelector.vue';

defineProps<{
  camino: ReturnType<typeof useCromoPath>;
  servicioId: number | null;
}>();

defineSlots<{
  'odf-accion'(props: { odf: OdfDelCamino }): unknown;
}>();
</script>

<style scoped>
.cromo-camino {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.cromo-camino__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.cromo-camino__titulo {
  margin: 0;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.cromo-camino__nota {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.45;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.cromo-camino__error {
  margin: 0;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  font-size: 11.5px;
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
}

.cromo-camino__aviso {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0;
  font-size: 11.5px;
  color: var(--color-state-warn);
}

.cromo-camino__esperando {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px 9px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
  font-size: 12px;
}

/* Reusa el `@keyframes spin` global de tokens.css en vez de definir uno local. */
.cromo-camino__spin {
  animation: spin 1s linear infinite;
}

.cromo-camino__meta {
  margin: 0;
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}

.cromo-camino__odfs {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.cromo-camino__odfs li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--color-accent) 8%, transparent);
}

.cromo-camino__odf-nombre {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  font-size: 12.5px;
}

.cromo-camino__odf-meta {
  font-size: 10.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

</style>
