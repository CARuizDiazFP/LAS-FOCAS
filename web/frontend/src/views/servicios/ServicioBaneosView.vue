<!--
  Nombre de archivo: ServicioBaneosView.vue
  Ubicación de archivo: web/frontend/src/views/servicios/ServicioBaneosView.vue
  Descripción: Eventos de baneo en los que participa un Servicio, como protegido o como afectado
-->
<template>
  <ServicioSeccionLayout
    :id-servicio="idServicio"
    titulo="Eventos de baneo"
    descripcion="Baneos en los que participó el Servicio, sea porque se lo protegió o porque se lo afectó para proteger a otro."
    :servicio="base.servicio.value"
    :loading="base.loading.value"
    :error="base.error.value"
  >
    <p v-if="cargando" class="baneos__estado">Cargando eventos…</p>
    <p v-else-if="error" class="baneos__estado is-error">{{ error }}</p>
    <p v-else-if="eventos.length === 0" class="baneos__estado">
      Este Servicio no participó en ningún baneo.
    </p>
    <template v-else>
      <p class="baneos__resumen">
        {{ eventos.length }} evento(s) · {{ activos }} activo(s)
      </p>
      <ul class="baneos__lista">
        <li v-for="evento in eventos" :key="evento.id" class="baneos__item">
          <span class="baneos__chips">
            <!-- Protegido y afectado son dos lecturas muy distintas de la misma fila. -->
            <span class="baneos__chip" :class="evento.rol === 'PROTEGIDO' ? 'is-ok' : 'is-warn'">
              {{ evento.rol === 'PROTEGIDO' ? 'Protegido' : 'Afectado' }}
            </span>
            <span class="baneos__chip" :class="evento.activo ? 'is-error' : 'is-idle'">
              {{ evento.activo ? 'Activo' : 'Cerrado' }}
            </span>
          </span>
          <span class="baneos__cuerpo">
            <span class="baneos__titulo">
              <template v-if="evento.ticket_asociado">Ticket {{ evento.ticket_asociado }}</template>
              <template v-else>Sin ticket</template>
              <span class="baneos__par">
                · protegido {{ evento.servicio_protegido_id }} · afectado
                {{ evento.servicio_afectado_id }}
              </span>
            </span>
            <span class="baneos__meta">
              {{ fecha(evento.fecha_inicio) }} → {{ evento.fecha_fin ? fecha(evento.fecha_fin) : 'sin cierre' }}
              <template v-if="evento.usuario_ejecutor"> · {{ evento.usuario_ejecutor }}</template>
            </span>
            <span v-if="evento.motivo" class="baneos__motivo">{{ evento.motivo }}</span>
          </span>
        </li>
      </ul>
    </template>
  </ServicioSeccionLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';

import { type ServicioBaneo, getBaneosServicio } from '../../api/servicioSecciones';
import { useServicioBase } from '../../composables/useServicioBase';
import ServicioSeccionLayout from './ServicioSeccionLayout.vue';

const route = useRoute();
const base = useServicioBase();

const idServicio = computed(() => String(route.params.idServicio ?? ''));
const eventos = ref<ServicioBaneo[]>([]);
const activos = ref(0);
const cargando = ref(false);
const error = ref('');

async function cargar(id: string): Promise<void> {
  const ok = await base.cargar(id);
  if (!ok || !base.servicio.value) return;
  cargando.value = true;
  error.value = '';
  try {
    const respuesta = await getBaneosServicio(base.servicio.value.id);
    eventos.value = respuesta.eventos;
    activos.value = respuesta.activos;
  } catch (err: unknown) {
    eventos.value = [];
    activos.value = 0;
    error.value = err instanceof Error ? err.message : 'No se pudieron cargar los baneos';
  } finally {
    cargando.value = false;
  }
}

function fecha(valor: string | null): string {
  if (!valor) return '—';
  const parsed = new Date(valor);
  return Number.isNaN(parsed.getTime()) ? valor : parsed.toLocaleString('es-AR');
}

onMounted(() => cargar(idServicio.value));
watch(idServicio, (id) => cargar(id));
</script>

<style scoped>
.baneos__estado,
.baneos__resumen {
  margin: 0;
  font-size: 13px;
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.baneos__estado.is-error {
  color: var(--color-state-error);
}

.baneos__lista {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.baneos__item {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.baneos__chips {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex-shrink: 0;
}

.baneos__chip {
  padding: 1px 7px;
  border-radius: var(--radius-pill);
  font-size: 9.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  text-align: center;
}

.baneos__chip.is-ok {
  background: color-mix(in srgb, var(--color-state-ok) 18%, transparent);
  color: var(--color-state-ok);
}

.baneos__chip.is-warn {
  background: color-mix(in srgb, var(--color-state-warn) 18%, transparent);
  color: var(--color-state-warn);
}

.baneos__chip.is-error {
  background: color-mix(in srgb, var(--color-state-error) 18%, transparent);
  color: var(--color-state-error);
}

.baneos__chip.is-idle {
  background: color-mix(in srgb, var(--color-text) 10%, transparent);
  color: color-mix(in srgb, var(--color-text) 60%, transparent);
}

.baneos__cuerpo {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.baneos__titulo {
  font-size: 12.5px;
}

.baneos__par,
.baneos__meta {
  font-size: 10.5px;
  font-variant-numeric: tabular-nums;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.baneos__motivo {
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}
</style>
