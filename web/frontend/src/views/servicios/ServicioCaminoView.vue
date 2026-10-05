<!--
  Nombre de archivo: ServicioCaminoView.vue
  Ubicación de archivo: web/frontend/src/views/servicios/ServicioCaminoView.vue
  Descripción: Camino óptico de un Servicio en su vista dedicada, en orden de canal — ODFs de
  Cromo ingerido, resolución en vivo contra Cromo, y el tracking manual sólo para regularizar
-->
<template>
  <ServicioSeccionLayout
    :id-servicio="idServicio"
    titulo="Camino óptico"
    descripcion="Las ODFs del Servicio según Cromo, su recorrido físico resuelto en vivo, y el tracking manual de regularización."
    :servicio="base.servicio.value"
    :loading="base.loading.value"
    :error="base.error.value"
  >
    <OdfsCromoPanel :servicio-id="base.servicio.value?.id ?? null" />

    <hr class="noc-rule" />

    <CromoCaminoPanel :camino="camino" :servicio-id="base.servicio.value?.id ?? null" />

    <div class="camino__acciones">
      <button
        class="btn subtle"
        type="button"
        :disabled="camino.pelos.value.length === 0 || camino.descargando.value"
        :title="
          camino.pelos.value.length === 0
            ? 'Cromo no tiene ningún pelo matcheado para este Servicio: no hay camino que trazar'
            : 'Descarga un .txt por camino del Servicio (o por cada pelo tildado, si cambiaste la selección), generado desde Cromo'
        "
        @click="descargar"
      >
        {{ etiquetaDescarga }}
      </button>
      <span v-if="camino.errorDescarga.value" class="camino__error">
        {{ camino.errorDescarga.value }}
      </span>
    </div>

    <!-- Tercer canal. Se monta siempre pero se pinta solo si ese Servicio tiene tracking cargado
         (27 de 14.147 en dev), así que no hace falta condicionarlo desde acá. -->
    <OdfsAsociadasPanel :id-origen="base.idOrigen.value" />
  </ServicioSeccionLayout>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';

import CromoCaminoPanel from '../../components/infra/CromoCaminoPanel.vue';
import OdfsAsociadasPanel from '../../components/servicios/detalle/OdfsAsociadasPanel.vue';
import OdfsCromoPanel from '../../components/servicios/detalle/OdfsCromoPanel.vue';
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
  if (camino.resolviendoCaminos.value) return 'Resolviendo caminos en Cromo…';
  if (camino.descargando.value) {
    const total = camino.descargaTotal.value;
    return total > 1 ? `Generando… ${camino.descargadosCount.value}/${total}` : 'Generando…';
  }
  // Con la selección automática son los caminos esperados del Servicio, no lo tildado.
  const cantidad = camino.cantidadDescarga.value;
  return cantidad > 1 ? `Trackings Cromo (${cantidad} .txt)` : 'Tracking Cromo (.txt)';
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
