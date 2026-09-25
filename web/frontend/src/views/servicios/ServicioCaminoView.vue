<!--
  Nombre de archivo: ServicioCaminoView.vue
  Ubicación de archivo: web/frontend/src/views/servicios/ServicioCaminoView.vue
  Descripción: Camino óptico de un Servicio en su vista dedicada — lo que declara Cromo
  (resolución, consistencia, secuencia, descarga de .txt) y las ODFs del archivo de tracking de ruta
-->
<template>
  <ServicioSeccionLayout
    :id-servicio="idServicio"
    titulo="Camino óptico"
    descripcion="Dos lecturas del recorrido físico: la que declara Cromo y la del archivo de tracking de la ruta."
    :servicio="base.servicio.value"
    :loading="base.loading.value"
    :error="base.error.value"
  >
    <CromoCaminoPanel :camino="camino" :servicio-id="base.servicio.value?.id ?? null" />

    <div class="camino__acciones">
      <button
        class="btn subtle"
        type="button"
        :disabled="camino.pelos.value.length === 0 || camino.descargando.value"
        :title="
          camino.pelos.value.length === 0
            ? 'Cromo no tiene ningún pelo matcheado para este Servicio: no hay camino que trazar'
            : 'Descarga un .txt por cada pelo tildado, generado desde Cromo'
        "
        @click="descargar"
      >
        {{ etiquetaDescarga }}
      </button>
      <span v-if="camino.errorDescarga.value" class="camino__error">
        {{ camino.errorDescarga.value }}
      </span>
    </div>

    <hr class="noc-rule" />

    <!-- Fuente distinta a todo lo de arriba: el tracking de ruta subido a mano, no Cromo. Vive acá
         y no en la ficha porque la ficha se compactó a tarjetas, y su tarjeta "Camino óptico" ya
         contaba estas ODFs sin tener dónde mostrarlas. -->
    <OdfsAsociadasPanel :id-origen="base.idOrigen.value" />
  </ServicioSeccionLayout>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';

import CromoCaminoPanel from '../../components/infra/CromoCaminoPanel.vue';
import OdfsAsociadasPanel from '../../components/servicios/detalle/OdfsAsociadasPanel.vue';
import { useCromoPath } from '../../composables/useCromoPath';
import { useServicioBase } from '../../composables/useServicioBase';
import ServicioSeccionLayout from './ServicioSeccionLayout.vue';

const route = useRoute();
const base = useServicioBase();
const camino = useCromoPath();

const idServicio = computed(() => String(route.params.idServicio ?? ''));

/** Dice cuántos archivos van a bajar y, durante la descarga, cuántos van: en frío cada pelo cuesta
 * entre 4,6 s y 14 s contra Cromo, así que sin progreso el operador cree que se colgó. */
const etiquetaDescarga = computed(() => {
  if (camino.descargando.value) {
    const total = camino.descargaTotal.value;
    return total > 1 ? `Generando… ${camino.descargadosCount.value}/${total}` : 'Generando…';
  }
  const tildados = camino.pelosSeleccionados.value.length;
  return tildados > 1 ? `Trackings Cromo (${tildados} .txt)` : 'Tracking Cromo (.txt)';
});

async function cargar(id: string): Promise<void> {
  camino.reset();
  const ok = await base.cargar(id);
  if (ok && base.servicio.value) {
    await camino.cargarPelos(base.servicio.value.id, { priorizarConector: true });
  }
}

async function descargar(): Promise<void> {
  if (!base.servicio.value) return;
  await camino.descargarTrackings(base.servicio.value.id);
}

onMounted(() => cargar(idServicio.value));
watch(idServicio, (id) => cargar(id));
// Resolver el camino puede dejar una request de hasta 30 s en vuelo al salir de la vista.
onBeforeUnmount(() => camino.cancelar());
</script>

<style scoped>
.camino__acciones {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 9px;
}

.camino__error {
  font-size: 11.5px;
  color: var(--color-state-error);
}
</style>
