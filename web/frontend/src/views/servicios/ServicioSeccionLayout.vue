<!--
  Nombre de archivo: ServicioSeccionLayout.vue
  Ubicación de archivo: web/frontend/src/views/servicios/ServicioSeccionLayout.vue
  Descripción: Marco común de las vistas dedicadas de una sección del Servicio — migas, cabecera
  con la identidad del Servicio y estados de carga/error, para que las cinco no diverjan
-->
<template>
  <section class="seccion">
    <nav class="seccion__migas" aria-label="Ruta de navegación">
      <RouterLink to="/servicios">Servicios</RouterLink>
      <span aria-hidden="true">›</span>
      <RouterLink :to="`/servicios/ID/${encodeURIComponent(idServicio)}`">
        {{ idServicio }}
      </RouterLink>
      <span aria-hidden="true">›</span>
      <span>{{ titulo }}</span>
    </nav>

    <header class="seccion__head">
      <div class="seccion__identidad">
        <span class="seccion__kicker">{{ titulo }}</span>
        <h1 class="seccion__h1">{{ servicio?.nombre_cliente || idServicio }}</h1>
        <p v-if="descripcion" class="seccion__descripcion">{{ descripcion }}</p>
      </div>
      <RouterLink
        class="btn subtle"
        :to="`/servicios/ID/${encodeURIComponent(idServicio)}`"
      >
        Volver al Servicio
      </RouterLink>
    </header>

    <hr class="noc-rule" />

    <p v-if="loading" class="seccion__estado">Cargando…</p>
    <p v-else-if="error" class="seccion__estado is-error">{{ error }}</p>
    <slot v-else></slot>
  </section>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router';

import type { ServicioItem } from '../../api/servicios';

defineProps<{
  idServicio: string;
  titulo: string;
  descripcion?: string;
  servicio: ServicioItem | null;
  loading: boolean;
  error: string;
}>();
</script>

<style scoped>
.seccion {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  /* Sólo el vertical: la canaleta lateral la pone `.app-shell__main` para todo el SPA. */
  padding-block: 22px 30px;
}

.seccion__migas {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.seccion__migas a {
  color: inherit;
}

.seccion__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  flex-wrap: wrap;
}

.seccion__identidad {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.seccion__kicker {
  font-size: 10.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.seccion__h1 {
  margin: 0;
  font-size: 20px;
}

.seccion__descripcion {
  margin: 0;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.seccion__estado {
  margin: 0;
  font-size: 13px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.seccion__estado.is-error {
  color: var(--color-state-error);
}
</style>
