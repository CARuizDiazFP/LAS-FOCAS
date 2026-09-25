<!--
  Nombre de archivo: ServicioHistoricoView.vue
  Ubicación de archivo: web/frontend/src/views/servicios/ServicioHistoricoView.vue
  Descripción: Histórico completo de IDs de un Servicio — el render vertical extenso, que salió de
  la ficha para que ésta quede compacta
-->
<template>
  <ServicioSeccionLayout
    :id-servicio="idServicio"
    titulo="Histórico de IDs"
    descripcion="Cadena de altas, bajas y cambios de identidad del Servicio."
    :servicio="base.servicio.value"
    :loading="base.loading.value"
    :error="base.error.value"
  >
    <ServiceTimelineDetalle :events="eventos" />
  </ServicioSeccionLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue';
import { useRoute } from 'vue-router';

import { historialIdsToTimelineEvents } from '../../api/servicios';
import ServiceTimelineDetalle from '../../components/servicios/ServiceTimelineDetalle.vue';
import { useServicioBase } from '../../composables/useServicioBase';
import ServicioSeccionLayout from './ServicioSeccionLayout.vue';

const route = useRoute();
const base = useServicioBase();

const idServicio = computed(() => String(route.params.idServicio ?? ''));
const eventos = computed(() => historialIdsToTimelineEvents(base.historialIds.value));

onMounted(() => base.cargar(idServicio.value));
watch(idServicio, (id) => base.cargar(id));
</script>
