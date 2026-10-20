<!--
  Nombre de archivo: AnalisisRetroactivoPanel.vue
  Ubicación de archivo: web/frontend/src/admin/components/arbitro/AnalisisRetroactivoPanel.vue
  Descripción: Panel del análisis retroactivo del árbitro de Cromo — lanza la corrida (todas las reglas o un subconjunto), la sigue por WebSocket y lista las últimas evaluaciones con su resumen por regla
-->
<template>
  <section class="analisis">
    <header class="analisis__cabecera">
      <h3>Análisis retroactivo</h3>
      <span v-if="enCurso !== null" class="analisis__en-curso" role="status">
        <i class="ph ph-circle-notch analisis__spin" aria-hidden="true"></i>
        En curso desde {{ desdeHora }}
      </span>
    </header>

    <div class="analisis__fila">
      <div class="analisis__reglas" role="group" aria-label="Reglas a evaluar">
        <span class="analisis__etiqueta">Reglas</span>
        <button
          type="button"
          :class="['analisis__chip', { 'is-active': seleccionadas.size === 0 }]"
          @click="seleccionadas = new Set()"
        >
          Todas
        </button>
        <button
          v-for="regla in reglas"
          :key="regla.codigo"
          type="button"
          :class="['analisis__chip', { 'is-active': seleccionadas.has(regla.codigo) }]"
          @click="toggleRegla(regla.codigo)"
        >
          {{ regla.codigo }}
        </button>
      </div>
      <button class="btn primary" type="button" :disabled="enCurso !== null || lanzando" @click="lanzar">
        <i class="ph ph-magnifying-glass-plus" aria-hidden="true"></i>
        Ejecutar análisis retroactivo
      </button>
    </div>

    <p v-if="error" class="analisis__error">{{ error }}</p>

    <details class="analisis__historial" open>
      <summary>Últimas evaluaciones ({{ evaluaciones.length }})</summary>
      <p v-if="!evaluaciones.length" class="analisis__vacio">Todavía no hay evaluaciones registradas.</p>
      <table v-else class="analisis__tabla">
        <thead>
          <tr>
            <th>#</th>
            <th>Estado</th>
            <th>Disparo</th>
            <th>Pedida por</th>
            <th>Inicio</th>
            <th>Duración</th>
            <th>Resumen por regla</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ev in evaluaciones" :key="ev.id">
            <td>{{ ev.id }}</td>
            <td>
              <span :class="['analisis__estado', `is-${ev.estado.toLowerCase()}`]">{{ ev.estado }}</span>
              <span v-if="ev.error" class="analisis__sub analisis__sub--error">{{ ev.error }}</span>
            </td>
            <td>{{ ev.disparo }}</td>
            <td>{{ ev.solicitada_por ?? '—' }}</td>
            <td>{{ fechaHora(ev.iniciada_en ?? ev.encolada_en) }}</td>
            <td>{{ duracion(ev) }}</td>
            <td>
              <ul v-if="resumenRegla(ev).length" class="analisis__resumen">
                <li v-for="[codigo, r] in resumenRegla(ev)" :key="codigo">
                  <strong>{{ codigo }}</strong>
                  <template v-if="r.error"> · <span class="analisis__sub--error">{{ r.error }}</span></template>
                  <template v-else>
                    · {{ r.nuevas ?? 0 }} nuevas · {{ r.aplicadas_auto ?? 0 }} AUTO · {{ r.obsoletas ?? 0 }} obsoletas ·
                    {{ r.revertidas ?? 0 }} revertidas
                    <span v-if="r.presupuesto_excedido" class="analisis__sub--warn">
                      · presupuesto excedido ({{ r.presupuesto_excedido }})
                    </span>
                  </template>
                </li>
              </ul>
              <span v-else class="analisis__sub">—</span>
            </td>
          </tr>
        </tbody>
      </table>
    </details>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';

import {
  ejecutarAnalisisRetroactivo,
  evaluacionIdDeError,
  listarEvaluaciones,
  listarReglas,
  type EvaluacionArbitro,
  type ReglaArbitro,
  type ResumenReglaEvaluacion,
} from '../../../api/arbitroCromo';
import { ApiError } from '../../../api/client';
import { useAdminNotifications } from '../../../composables/useAdminNotifications';

const emit = defineEmits<{
  /** Terminó una evaluación: reglas que tocó (vacío = todas) para refrescar las propuestas. */
  (e: 'terminada', reglas: string[]): void;
}>();

const POLL_MS = 15000;

const reglas = ref<ReglaArbitro[]>([]);
const seleccionadas = ref(new Set<string>());
const evaluaciones = ref<EvaluacionArbitro[]>([]);
const enCurso = ref<number | null>(null);
const lanzando = ref(false);
const error = ref('');
let poll: ReturnType<typeof setInterval> | null = null;

const desdeHora = computed(() => {
  const ev = evaluaciones.value.find((e) => e.id === enCurso.value);
  return ev ? fechaHora(ev.iniciada_en ?? ev.encolada_en, true) : '—';
});

function fechaHora(valor: string | null, soloHora = false): string {
  if (!valor) return '—';
  const d = new Date(valor);
  if (Number.isNaN(d.getTime())) return valor;
  return soloHora
    ? d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' });
}

function duracion(ev: EvaluacionArbitro): string {
  if (!ev.iniciada_en || !ev.terminada_en) return '—';
  const seg = Math.max(0, Math.round((Date.parse(ev.terminada_en) - Date.parse(ev.iniciada_en)) / 1000));
  return seg >= 60 ? `${Math.floor(seg / 60)} min ${seg % 60} s` : `${seg} s`;
}

function resumenRegla(ev: EvaluacionArbitro): [string, ResumenReglaEvaluacion][] {
  return Object.entries(ev.resumen?.por_regla ?? {});
}

function toggleRegla(codigo: string): void {
  const nuevo = new Set(seleccionadas.value);
  if (nuevo.has(codigo)) nuevo.delete(codigo);
  else nuevo.add(codigo);
  seleccionadas.value = nuevo;
}

function ajustarPoll(): void {
  if (enCurso.value !== null && !poll) poll = setInterval(() => void cargar(), POLL_MS);
  else if (enCurso.value === null && poll) {
    clearInterval(poll);
    poll = null;
  }
}

/** Recarga el historial; si la corrida que seguíamos terminó (el WS pudo perderse), avisa. */
async function cargar(): Promise<void> {
  const seguida = enCurso.value;
  try {
    const respuesta = await listarEvaluaciones(10);
    evaluaciones.value = respuesta.items;
    enCurso.value = respuesta.en_curso;
    if (seguida !== null && respuesta.en_curso === null) terminoEvaluacion(seguida);
  } catch (err: unknown) {
    error.value = err instanceof Error ? err.message : 'No se pudo consultar el historial de evaluaciones';
  }
  ajustarPoll();
}

function terminoEvaluacion(id: number): void {
  const ev = evaluaciones.value.find((e) => e.id === id);
  emit('terminada', ev?.reglas ?? []);
}

async function lanzar(): Promise<void> {
  const alcance = seleccionadas.value.size ? [...seleccionadas.value].join(', ') : 'todas las reglas';
  if (
    !window.confirm(
      `El análisis retroactivo evalúa todo el inventario con ${alcance} y puede aplicar cambios en modo AUTO. ¿Ejecutarlo?`,
    )
  )
    return;
  lanzando.value = true;
  error.value = '';
  try {
    const { evaluacion_id } = await ejecutarAnalisisRetroactivo([...seleccionadas.value]);
    enCurso.value = evaluacion_id;
    await cargar();
    if (enCurso.value === null) enCurso.value = evaluacion_id; // aún no figura en la lista: se sigue por WS
    ajustarPoll();
  } catch (err: unknown) {
    const id = evaluacionIdDeError(err);
    if (err instanceof ApiError && err.status === 409) {
      error.value = 'Ya hay un análisis retroactivo en curso; se sigue ese.';
      if (id !== null) enCurso.value = id;
      await cargar();
    } else if (err instanceof ApiError && err.status === 503) {
      error.value = 'No se pudo encolar el análisis (el worker no está disponible). Reintentá en un momento.';
      await cargar();
    } else {
      error.value = err instanceof Error ? err.message : 'No se pudo lanzar el análisis retroactivo';
    }
  } finally {
    lanzando.value = false;
  }
}

const { on } = useAdminNotifications();
on('arbitro_cromo_en_curso', (mensaje) => {
  enCurso.value = Number(mensaje.evaluacion_id);
  void cargar();
});
on('arbitro_cromo_evaluado', (mensaje) => {
  const id = Number(mensaje.evaluacion_id);
  enCurso.value = null;
  void cargar().then(() => terminoEvaluacion(id));
});

onMounted(async () => {
  try {
    reglas.value = await listarReglas();
  } catch {
    // El selector es accesorio: sin reglas queda sólo "Todas".
  }
  await cargar();
});

onBeforeUnmount(() => {
  if (poll) clearInterval(poll);
});
</script>

<style scoped>
.analisis {
  margin-bottom: 14px;
  padding: 12px 14px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.analisis__cabecera { display: flex; align-items: center; gap: 12px; }
.analisis__cabecera h3 { margin: 0; font-size: 14px; font-weight: 500; }

.analisis__en-curso {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--color-state-warn);
}

.analisis__fila { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: space-between; }
.analisis__reglas { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

.analisis__etiqueta {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-neutral-500);
}

.analisis__chip {
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  font-size: 11.5px;
  cursor: pointer;
  border: 1px solid var(--color-divider);
  background: transparent;
  color: color-mix(in srgb, var(--color-text) 66%, transparent);
}

.analisis__chip:hover { border-color: var(--color-accent); }

.analisis__chip.is-active {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 12%, transparent);
  color: var(--color-accent-200);
}

.analisis__error {
  margin: 0;
  padding: 8px 12px;
  border-radius: var(--radius-md);
  font-size: 12.5px;
  background: color-mix(in srgb, var(--color-state-error) 14%, transparent);
  color: var(--color-state-error);
}

.analisis__historial { font-size: 12.5px; color: var(--color-neutral-500); }
.analisis__historial summary { cursor: pointer; }
.analisis__vacio { margin: 8px 0 0; font-size: 12px; }

.analisis__tabla { width: 100%; margin-top: 8px; border-collapse: collapse; font-size: 12px; }

.analisis__tabla th {
  text-align: left;
  font-weight: 500;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 6px 8px;
  color: var(--color-neutral-500);
  border-bottom: 1px solid var(--color-divider);
}

.analisis__tabla td {
  padding: 6px 8px;
  vertical-align: top;
  border-bottom: 1px solid var(--color-neutral-800);
  color: var(--color-text);
}

.analisis__estado { font-weight: 500; }
.analisis__estado.is-en_cola,
.analisis__estado.is-en_curso { color: var(--color-state-warn); }
.analisis__estado.is-fallida { color: var(--color-state-error); }
.analisis__estado.is-ok { color: var(--color-state-ok); }

.analisis__sub { display: block; font-size: 11px; color: color-mix(in srgb, var(--color-text) 50%, transparent); }
.analisis__sub--error { color: var(--color-state-error); }
.analisis__sub--warn { color: var(--color-state-warn); }

.analisis__resumen { margin: 0; padding: 0; list-style: none; font-size: 11.5px; }

.analisis__spin { animation: analisis-spin 1s linear infinite; }

@keyframes analisis-spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
