<!--
  Nombre de archivo: ServiceTimeline.vue
  Ubicación de archivo: web/frontend/src/components/servicios/ServiceTimeline.vue
  Descripción: Línea de tiempo genérica de eventos — historial de upgrades de ID hoy, Reclamos/Ingresos/Mantenimientos a futuro
-->
<template>
  <ol v-if="events.length > 0" class="service-timeline">
    <li v-for="event in events" :key="event.id" class="service-timeline__item">
      <div class="service-timeline__marker" aria-hidden="true"></div>
      <div class="service-timeline__body">
        <div class="service-timeline__headline">
          <strong>{{ event.titulo }}</strong>
          <span v-if="event.estado" :class="['service-timeline__chip', estadoClase(event.estado)]">
            {{ event.estado }}
          </span>
        </div>
        <span v-if="event.fecha" class="service-timeline__fecha">{{ formatearFecha(event.fecha) }}</span>
        <p v-if="event.descripcion" class="service-timeline__descripcion">{{ event.descripcion }}</p>
      </div>
    </li>
  </ol>
  <p v-else class="service-timeline__empty">Sin eventos para mostrar.</p>
</template>

<script setup lang="ts">
import type { TimelineEvent } from '../../types/timeline';

defineProps<{
  events: TimelineEvent[];
}>();

const ESTADOS_OK = new Set(['instalado', 'activo', 'vigente']);
const ESTADOS_ERROR = new Set(['dado baja', 'baja']);

function estadoClase(estado: string): string {
  const valor = estado.trim().toLowerCase();
  if (ESTADOS_OK.has(valor)) return 'is-ok';
  if (ESTADOS_ERROR.has(valor)) return 'is-error';
  return 'is-idle';
}

const FECHA_SOLO_DIA = /^(\d{4})-(\d{2})-(\d{2})$/;

function formatearFecha(fecha: string): string {
  // `fecha_instalacion`/`fecha_baja` llegan como fecha pura ("2019-11-01": campo `date` de
  // Pydantic, sin hora ni offset). `new Date("2019-11-01")` la interpreta como medianoche UTC y,
  // formateada en Argentina (UTC-3), muestra el día ANTERIOR ("31/10/2019"). Por eso la fecha
  // pura se parsea a mano y se construye con el constructor de 3 argumentos, que es hora LOCAL
  // (nunca UTC) — así el día formateado es el mismo en cualquier zona horaria.
  const soloDia = FECHA_SOLO_DIA.exec(fecha.trim());
  if (soloDia) {
    const [, anio, mes, dia] = soloDia;
    const local = new Date(Number(anio), Number(mes) - 1, Number(dia));
    const esFechaReal =
      !Number.isNaN(local.getTime()) &&
      local.getFullYear() === Number(anio) &&
      local.getMonth() === Number(mes) - 1 &&
      local.getDate() === Number(dia);
    // Una fecha imposible ("2019-13-45") cae al fallback de siempre: se devuelve el string crudo.
    if (esFechaReal) {
      return local.toLocaleDateString('es-AR', { year: 'numeric', month: '2-digit', day: '2-digit' });
    }
    return fecha;
  }

  const parsed = new Date(fecha);
  if (Number.isNaN(parsed.getTime())) return fecha;
  return parsed.toLocaleDateString('es-AR', { year: 'numeric', month: '2-digit', day: '2-digit' });
}
</script>

<style scoped>
.service-timeline {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}

.service-timeline__item {
  display: grid;
  gap: 4px;
  padding: 10px 0 10px 16px;
  margin-left: 5px;
  border-left: 2px solid var(--color-divider);
}

.service-timeline__item:last-child {
  border-left-color: transparent;
}

.service-timeline__marker {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: var(--color-accent-success);
  margin-left: -23px;
  margin-bottom: -12px;
}

.service-timeline__body {
  display: grid;
  gap: 4px;
}

.service-timeline__headline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.service-timeline__fecha {
  font-size: 0.8rem;
  color: var(--muted);
}

.service-timeline__descripcion {
  margin: 0;
  font-size: 0.85rem;
  color: var(--muted);
}

.service-timeline__chip {
  border-radius: 999px;
  padding: 2px 10px;
  font-size: 0.7rem;
  font-weight: 700;
}

.service-timeline__chip.is-ok {
  background: color-mix(in srgb, var(--success) 18%, transparent);
  color: var(--success);
}

.service-timeline__chip.is-error {
  background: color-mix(in srgb, var(--error) 18%, transparent);
  color: var(--error);
}

.service-timeline__chip.is-idle {
  background: color-mix(in srgb, var(--muted) 18%, transparent);
  color: var(--muted);
}

.service-timeline__empty {
  color: var(--muted);
  font-size: 0.85rem;
}
</style>
