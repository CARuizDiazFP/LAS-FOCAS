<!--
  Nombre de archivo: AdminIngestaCromo.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminIngestaCromo.vue
  Descripción: Vista admin para disparar y seguir en vivo una corrida de ingesta de inventario FO desde Cromo Red
-->
<template>
  <section class="admin-ingesta">
    <AdminPageHeader
      kicker="Ingesta · Cromo Red"
      title="Ingesta de Cromo"
      subtitle="Trae el inventario de fibra óptica (botellas, cables, tubos, pelos, fusiones) desde Cromo Red. Sólo lectura sobre Cromo — nunca escribe ahí."
    />

    <!-- Card: scheduler automático (Etapa 7) -->
    <div v-if="scheduler.cargando" style="color:var(--muted);padding:12px 0">Cargando configuración del scheduler…</div>
    <div v-else class="two-col">
      <article class="card ingesta-card">
        <header class="ingesta-card__header">
          <h2>Scheduler automático</h2>
        </header>

        <form @submit.prevent="guardarScheduler">
          <div class="toggle-row">
            <label class="toggle-wrap">
              <input type="checkbox" v-model="scheduler.habilitado" />
              <span class="toggle-slider" />
            </label>
            <span>Corrida periódica activa</span>
          </div>
          <p class="hint">
            Corre en el worker dedicado (<code>cromo_worker</code>), separado del panel. Empieza
            deshabilitado a propósito: activarlo dispara corridas reales contra Cromo sin supervisión.
          </p>

          <label>Intervalo de ejecución (horas)</label>
          <input v-model.number="scheduler.intervaloHoras" type="number" min="1" required />

          <label>Hora de inicio del ciclo <span style="color:var(--muted);font-size:0.8rem">(GMT -3)</span></label>
          <select v-model="scheduler.horaInicio">
            <option :value="null">Sin horario fijo — comenzar de inmediato</option>
            <option v-for="h in 24" :key="h - 1" :value="h - 1">{{ String(h - 1).padStart(2, '0') }}:00 hs</option>
          </select>

          <label>Clases de botella a incluir</label>
          <div class="clases-grid">
            <label v-for="c in CROMO_CATALOGO_BOTELLAS" :key="c.clase" class="clase-check">
              <input
                type="checkbox"
                :checked="clasesSchedulerSeleccionadas.has(c.clase)"
                @change="toggleClaseScheduler(c.clase)"
              />
              <span>{{ c.clase }}<template v-if="c.etiqueta"> · {{ c.etiqueta }}</template></span>
            </label>
          </div>

          <label>Tamaño de página (psize)</label>
          <select v-model.number="scheduler.psize">
            <option v-for="p in CROMO_PSIZE_OPCIONES" :key="p" :value="p">{{ p }}</option>
          </select>

          <label>Máximo de páginas (opcional)</label>
          <input v-model="scheduler.maxPaginasInput" type="number" min="1" placeholder="Sin límite (corrida real completa)" />
          <p class="hint">Sin límite: barrido completo real, del orden de horas. Usar un valor bajo sólo para probar el ciclo.</p>

          <button class="btn primary" type="submit" :disabled="scheduler.guardando || clasesSchedulerSeleccionadas.size === 0">
            {{ scheduler.guardando ? 'Guardando…' : 'Guardar configuración' }}
          </button>
        </form>

        <p v-if="scheduler.msg" :class="['msg', scheduler.error ? 'err' : 'ok', 'visible']">{{ scheduler.msg }}</p>
      </article>

      <article class="card ingesta-card">
        <header class="ingesta-card__header">
          <h2>Estado del worker</h2>
        </header>

        <div style="text-align:center;padding:20px 0">
          <span class="status-badge" :class="schedulerHealth.estadoClase">
            <span class="status-dot" :class="schedulerHealth.estadoClase" />
            {{ schedulerHealth.etiqueta }}
          </span>
        </div>

        <div class="info-row">
          <span class="info-label">Última ejecución</span>
          <span class="info-value">{{ formatFecha(schedulerHealth.ultimaEjecucion) }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">Último error</span>
          <span class="info-value">{{ schedulerHealth.ultimoError || 'Ninguno' }}</span>
        </div>

        <button
          type="button"
          class="btn primary"
          style="width:100%;margin-top:16px"
          :disabled="schedulerHealth.cargando"
          @click="verificarSaludScheduler"
        >
          {{ schedulerHealth.cargando ? 'Verificando…' : 'Verificar estado' }}
        </button>
        <button
          type="button"
          class="btn subtle"
          style="width:100%;margin-top:8px"
          :disabled="ejecutandoAhora"
          @click="ejecutarSchedulerAhora"
        >
          {{ ejecutandoAhora ? 'Ejecutando…' : 'Ejecutar ahora' }}
        </button>
      </article>
    </div>

    <!-- Card: disparar corrida -->
    <article class="card ingesta-card">
      <header class="ingesta-card__header">
        <h2>Nueva corrida</h2>
        <span v-if="corridaActiva" class="ingesta-card__chip">En curso</span>
      </header>

      <form @submit.prevent="onDisparar">
        <label>Clases de botella a incluir</label>
        <div class="clases-grid">
          <label v-for="c in CROMO_CATALOGO_BOTELLAS" :key="c.clase" class="clase-check">
            <input
              type="checkbox"
              :checked="clasesSeleccionadas.has(c.clase)"
              :disabled="disparando || corridaActiva"
              @change="toggleClase(c.clase)"
            />
            <span>{{ c.clase }}<template v-if="c.etiqueta"> · {{ c.etiqueta }}</template></span>
            <em v-if="!c.homologada" class="clase-check__nota">no homologada</em>
          </label>
          <label class="clase-check clase-check--excluida" :title="CROMO_CLASE_EXCLUIDA.motivo">
            <input type="checkbox" disabled />
            <span>{{ CROMO_CLASE_EXCLUIDA.clase }} · excluida</span>
          </label>
        </div>
        <p class="hint">
          Cables (class 51) se barren siempre en la Fase 2; tubos, pelos y fusiones llegan con su
          botella o cable. La clase 120 nunca se ingiere ({{ CROMO_CLASE_EXCLUIDA.motivo.toLowerCase() }}).
        </p>

        <label>Tamaño de página (psize)</label>
        <select v-model.number="psize" :disabled="disparando || corridaActiva">
          <option v-for="p in CROMO_PSIZE_OPCIONES" :key="p" :value="p">{{ p }}</option>
        </select>
        <p class="hint">Producción arranca en 5. Valores más altos traen páginas más pesadas.</p>

        <label>Máximo de páginas (opcional)</label>
        <input
          v-model="maxPaginasInput"
          type="number"
          min="1"
          placeholder="Sin límite"
          :disabled="disparando || corridaActiva"
        />
        <p class="hint">Poner 1 para modo prueba: trae una sola página por fase y corta.</p>

        <button class="btn primary" type="submit" :disabled="disparando || corridaActiva || clasesSeleccionadas.size === 0">
          {{ disparando ? 'Iniciando…' : 'Iniciar corrida' }}
        </button>
      </form>

      <p v-if="feedback" :class="['msg', feedbackType === 'ok' ? 'ok' : 'err', 'visible']">{{ feedback }}</p>
    </article>

    <!-- Card: progreso en vivo -->
    <article v-if="corridaActual" class="card ingesta-card">
      <header class="ingesta-card__header">
        <h2>Corrida #{{ corridaActual.id }}</h2>
        <span class="ingesta-card__chip" :class="`ingesta-card__chip--${estadoClase(corridaActual.estado)}`">
          {{ corridaActual.estado }}
        </span>
      </header>

      <p class="fase-actual">{{ faseActual || 'Iniciando…' }}</p>

      <div class="progress-wrap" role="status" aria-live="polite">
        <div class="progress-track">
          <div class="progress-bar" :style="{ width: `${porcentajeProgreso}%` }"></div>
        </div>
        <div class="progress-meta">
          <span>{{ corridaActual.leidas }} leídas{{ corridaActual.total_objetivo ? ` / ~${corridaActual.total_objetivo}` : '' }}</span>
          <span>{{ porcentajeProgreso }}%</span>
        </div>
      </div>

      <dl class="summary-grid">
        <div>
          <dt>Creadas</dt>
          <dd>{{ corridaActual.creadas }}</dd>
        </div>
        <div>
          <dt>Actualizadas</dt>
          <dd>{{ corridaActual.actualizadas }}</dd>
        </div>
        <div>
          <dt>Sin cambios</dt>
          <dd>{{ corridaActual.sin_cambios }}</dd>
        </div>
        <div>
          <dt>Errores</dt>
          <dd :class="{ 'dd--err': corridaActual.errores > 0 }">{{ corridaActual.errores }}</dd>
        </div>
        <div>
          <dt>Refs. colgadas</dt>
          <dd :class="{ 'dd--warn': corridaActual.refs_colgadas > 0 }">{{ corridaActual.refs_colgadas }}</dd>
        </div>
      </dl>

      <details v-if="erroresRecientes.length > 0" class="errores-detalle">
        <summary>Ver errores recientes ({{ erroresRecientes.length }})</summary>
        <ul class="errores-list">
          <li v-for="(err, i) in erroresRecientes" :key="i">
            n_id={{ err.n_id ?? '—' }} clase={{ err.clase ?? '—' }}: {{ err.detalle ?? 'sin detalle' }}
          </li>
        </ul>
      </details>

      <button v-if="corridaActiva" class="btn subtle" type="button" :disabled="cancelando" @click="onCancelar">
        {{ cancelando ? 'Cancelando…' : 'Cancelar corrida' }}
      </button>
    </article>

    <!-- Card: histórico -->
    <article class="card ingesta-card">
      <header class="ingesta-card__header">
        <h2>Histórico de corridas</h2>
        <button class="btn subtle" type="button" @click="cargarHistorico">Refrescar</button>
      </header>

      <p v-if="cargandoHistorico" class="hint">Cargando…</p>
      <table v-else-if="historico.length > 0" class="tabla-historico">
        <thead>
          <tr>
            <th>ID</th>
            <th>Usuario</th>
            <th>Estado</th>
            <th>Leídas</th>
            <th>Creadas</th>
            <th>Actualizadas</th>
            <th>Sin cambios</th>
            <th>Errores</th>
            <th>Iniciada</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in historico" :key="c.id" class="tabla-historico__fila" @click="verDetalle(c.id)">
            <td>{{ c.id }}</td>
            <td>{{ c.usuario }}</td>
            <td><span class="ingesta-card__chip" :class="`ingesta-card__chip--${estadoClase(c.estado)}`">{{ c.estado }}</span></td>
            <td>{{ c.leidas }}</td>
            <td>{{ c.creadas }}</td>
            <td>{{ c.actualizadas }}</td>
            <td>{{ c.sin_cambios }}</td>
            <td :class="{ 'dd--err': c.errores > 0 }">{{ c.errores }}</td>
            <td>{{ formatFecha(c.iniciada_at) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="hint">Todavía no hay corridas registradas.</p>
    </article>

    <!-- Modal: detalle de una corrida -->
    <dialog ref="dialogDetalleEl" class="detalle-modal" @click.self="cerrarDetalle">
      <div class="modal-content" v-if="detalle">
        <div class="modal-header">
          <strong>Corrida #{{ detalle.corrida.id }}</strong>
          <button class="close-btn" type="button" aria-label="Cerrar" @click="cerrarDetalle">×</button>
        </div>
        <dl class="summary-grid">
          <div><dt>Estado</dt><dd>{{ detalle.corrida.estado }}</dd></div>
          <div><dt>Leídas</dt><dd>{{ detalle.corrida.leidas }}</dd></div>
          <div><dt>Errores</dt><dd>{{ detalle.corrida.errores }}</dd></div>
          <div><dt>Refs. colgadas</dt><dd>{{ detalle.corrida.refs_colgadas }}</dd></div>
        </dl>
        <h3>Últimos eventos</h3>
        <ul class="eventos-list">
          <li v-for="ev in detalle.eventos" :key="ev.id">
            <strong>{{ ev.accion }}</strong>
            <template v-if="ev.n_id"> n_id={{ ev.n_id }} clase={{ ev.clase }}</template>
            <span v-if="ev.detalle" class="eventos-list__detalle">{{ ev.detalle }}</span>
          </li>
        </ul>
      </div>
    </dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';

import AdminPageHeader from '../components/AdminPageHeader.vue';
import {
  CROMO_CATALOGO_BOTELLAS,
  CROMO_CLASE_EXCLUIDA,
  CROMO_PSIZE_OPCIONES,
  cancelarIngestaCromo,
  dispararSchedulerCromo,
  guardarConfigSchedulerCromo,
  iniciarIngestaCromo,
  obtenerConfigSchedulerCromo,
  obtenerDetalleCromo,
  obtenerHistoricoCromo,
  obtenerSaludWorkerCromo,
  streamUrlIngestaCromo,
  type CromoCorrida,
  type CromoDetalle,
  type CromoPsize,
} from '../../api/cromo';

const clasesSeleccionadas = ref<Set<number>>(
  new Set(CROMO_CATALOGO_BOTELLAS.filter((c) => c.seleccionablePorDefecto).map((c) => c.clase)),
);
const psize = ref<CromoPsize>(5);
const maxPaginasInput = ref('');

const disparando = ref(false);
const cancelando = ref(false);
const feedback = ref('');
const feedbackType = ref<'ok' | 'err'>('ok');

const corridaActual = ref<CromoCorrida | null>(null);
const faseActual = ref('');
const erroresRecientes = ref<Array<{ n_id: number | null; clase: number | null; detalle: string | null }>>([]);

const historico = ref<CromoCorrida[]>([]);
const cargandoHistorico = ref(false);

const detalle = ref<CromoDetalle | null>(null);
const dialogDetalleEl = ref<HTMLDialogElement | null>(null);

let eventSource: EventSource | null = null;

// ── Scheduler automático (Etapa 7) — formulario independiente del de "Nueva corrida" ────────────
const clasesSchedulerSeleccionadas = ref<Set<number>>(new Set());
const scheduler = ref({
  habilitado: false,
  intervaloHoras: 24,
  horaInicio: null as number | null,
  psize: 5 as CromoPsize,
  maxPaginasInput: '',
  cargando: true,
  guardando: false,
  msg: '',
  error: false,
});
const schedulerHealth = ref({
  verificado: false,
  cargando: false,
  estadoClase: 'unknown' as 'ok' | 'offline' | 'unknown',
  etiqueta: 'Sin verificar',
  ultimaEjecucion: null as string | null,
  ultimoError: null as string | null,
});
const ejecutandoAhora = ref(false);

const corridaActiva = computed(() => corridaActual.value?.estado === 'EN_CURSO');
const porcentajeProgreso = computed(() => {
  const c = corridaActual.value;
  if (!c || !c.total_objetivo) return 0;
  return Math.min(100, Math.round((c.leidas / c.total_objetivo) * 100));
});

function estadoClase(estado: string): string {
  if (estado === 'EN_CURSO') return 'info';
  if (estado === 'OK') return 'ok';
  if (estado === 'OK_CON_ERRORES') return 'warn';
  if (estado === 'CANCELADA') return 'warn';
  return 'err';
}

function formatFecha(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('es-AR');
}

function toggleClase(clase: number): void {
  if (clasesSeleccionadas.value.has(clase)) {
    clasesSeleccionadas.value.delete(clase);
  } else {
    clasesSeleccionadas.value.add(clase);
  }
  // Forzar reactividad: Set mutado in-place no dispara watchers de plantilla por sí solo.
  clasesSeleccionadas.value = new Set(clasesSeleccionadas.value);
}

function cerrarStream(): void {
  eventSource?.close();
  eventSource = null;
}

function conectarStream(corridaId: number): void {
  cerrarStream();
  const es = new EventSource(streamUrlIngestaCromo(corridaId));
  eventSource = es;

  es.addEventListener('inicio', (ev) => {
    const data = JSON.parse((ev as MessageEvent).data);
    if (corridaActual.value) corridaActual.value.total_objetivo = data.total_objetivo;
  });

  es.addEventListener('fase', (ev) => {
    const data = JSON.parse((ev as MessageEvent).data);
    faseActual.value = data.descripcion ?? data.fase;
  });

  es.addEventListener('pagina', (ev) => {
    const data = JSON.parse((ev as MessageEvent).data);
    if (!corridaActual.value) return;
    corridaActual.value.leidas = data.leidas;
    corridaActual.value.creadas = data.creadas;
    corridaActual.value.actualizadas = data.actualizadas;
    corridaActual.value.sin_cambios = data.sin_cambios;
    corridaActual.value.errores = data.errores;
  });

  // El evento nativo de EventSource también se llama "error" (caídas de conexión, sin .data);
  // el nuestro es un evento SSE con nombre "error" y viene como MessageEvent con .data poblado.
  es.addEventListener('error', (ev) => {
    const raw = (ev as MessageEvent).data;
    if (!raw) return;
    try {
      const data = JSON.parse(raw);
      erroresRecientes.value = [data, ...erroresRecientes.value].slice(0, 20);
    } catch {
      // payload no-JSON: se ignora, no es un evento de negocio.
    }
  });

  es.addEventListener('resumen', (ev) => {
    const data = JSON.parse((ev as MessageEvent).data);
    if (corridaActual.value) {
      corridaActual.value.estado = data.estado;
      corridaActual.value.leidas = data.leidas;
      corridaActual.value.creadas = data.creadas;
      corridaActual.value.actualizadas = data.actualizadas;
      corridaActual.value.sin_cambios = data.sin_cambios;
      corridaActual.value.errores = data.errores;
      corridaActual.value.refs_colgadas = data.refs_colgadas;
    }
    cerrarStream();
    cargarHistorico();
  });
}

async function onDisparar(): Promise<void> {
  feedback.value = '';
  disparando.value = true;
  erroresRecientes.value = [];
  faseActual.value = '';
  try {
    // Vue castea automáticamente a Number en cada evento `input` sólo por ser type="number" (aun sin
    // el modificador .number) — en runtime `.value` puede terminar siendo number, no string. String()
    // lo normaliza antes de `.trim()` sin importar cuál de los dos haya quedado.
    const maxPaginasTexto = String(maxPaginasInput.value ?? '').trim();
    const maxPaginas = maxPaginasTexto ? Number(maxPaginasTexto) : null;
    const { corrida_id } = await iniciarIngestaCromo({
      psize: psize.value,
      maxPaginas,
      clases: Array.from(clasesSeleccionadas.value),
    });
    corridaActual.value = {
      id: corrida_id,
      usuario: '',
      estado: 'EN_CURSO',
      params: {},
      total_objetivo: null,
      leidas: 0,
      creadas: 0,
      actualizadas: 0,
      sin_cambios: 0,
      errores: 0,
      refs_colgadas: 0,
      iniciada_at: new Date().toISOString(),
      finalizada_at: null,
    };
    conectarStream(corrida_id);
  } catch (err: unknown) {
    feedbackType.value = 'err';
    feedback.value = err instanceof Error ? err.message : 'No se pudo iniciar la corrida';
  } finally {
    disparando.value = false;
  }
}

async function onCancelar(): Promise<void> {
  if (!corridaActual.value) return;
  cancelando.value = true;
  try {
    await cancelarIngestaCromo(corridaActual.value.id);
  } catch (err: unknown) {
    feedbackType.value = 'err';
    feedback.value = err instanceof Error ? err.message : 'No se pudo cancelar la corrida';
  } finally {
    cancelando.value = false;
  }
}

async function cargarHistorico(): Promise<void> {
  cargandoHistorico.value = true;
  try {
    const resultado = await obtenerHistoricoCromo(10, 0);
    historico.value = resultado.corridas;

    const masReciente = resultado.corridas[0];
    if (masReciente && masReciente.estado === 'EN_CURSO' && !corridaActual.value) {
      corridaActual.value = masReciente;
      conectarStream(masReciente.id);
    }
  } catch {
    // El histórico es informativo — un fallo puntual no debe romper el resto de la vista.
  } finally {
    cargandoHistorico.value = false;
  }
}

async function verDetalle(corridaId: number): Promise<void> {
  try {
    detalle.value = await obtenerDetalleCromo(corridaId);
    dialogDetalleEl.value?.showModal();
  } catch (err: unknown) {
    feedbackType.value = 'err';
    feedback.value = err instanceof Error ? err.message : 'No se pudo cargar el detalle';
  }
}

function cerrarDetalle(): void {
  dialogDetalleEl.value?.close();
}

function toggleClaseScheduler(clase: number): void {
  if (clasesSchedulerSeleccionadas.value.has(clase)) {
    clasesSchedulerSeleccionadas.value.delete(clase);
  } else {
    clasesSchedulerSeleccionadas.value.add(clase);
  }
  clasesSchedulerSeleccionadas.value = new Set(clasesSchedulerSeleccionadas.value);
}

async function cargarConfigScheduler(): Promise<void> {
  scheduler.value.cargando = true;
  try {
    const cfg = await obtenerConfigSchedulerCromo();
    scheduler.value.habilitado = cfg.habilitado;
    scheduler.value.intervaloHoras = cfg.intervalo_horas;
    scheduler.value.horaInicio = cfg.hora_inicio;
    scheduler.value.psize = cfg.psize;
    scheduler.value.maxPaginasInput = cfg.max_paginas != null ? String(cfg.max_paginas) : '';
    clasesSchedulerSeleccionadas.value = new Set(cfg.clases);
    schedulerHealth.value.ultimaEjecucion = cfg.ultima_ejecucion;
    schedulerHealth.value.ultimoError = cfg.ultimo_error;
  } catch {
    // Sin config todavía visible — el form queda con los defaults declarados arriba.
  } finally {
    scheduler.value.cargando = false;
  }
}

async function guardarScheduler(): Promise<void> {
  scheduler.value.guardando = true;
  scheduler.value.msg = '';
  try {
    const raw = String(scheduler.value.maxPaginasInput ?? '').trim();
    await guardarConfigSchedulerCromo({
      habilitado: scheduler.value.habilitado,
      intervaloHoras: scheduler.value.intervaloHoras,
      horaInicio: scheduler.value.horaInicio,
      psize: scheduler.value.psize,
      maxPaginas: raw ? Number(raw) : null,
      clases: Array.from(clasesSchedulerSeleccionadas.value),
    });
    scheduler.value.msg = 'Configuración guardada.';
    scheduler.value.error = false;
    await verificarSaludScheduler();
  } catch (err: unknown) {
    scheduler.value.msg = err instanceof Error ? err.message : 'No se pudo guardar la configuración.';
    scheduler.value.error = true;
  } finally {
    scheduler.value.guardando = false;
  }
}

async function verificarSaludScheduler(): Promise<void> {
  schedulerHealth.value.cargando = true;
  try {
    const data = await obtenerSaludWorkerCromo();
    const activo = data.status === 'ok';
    schedulerHealth.value.estadoClase = activo ? 'ok' : 'offline';
    schedulerHealth.value.etiqueta = activo ? 'Activo' : data.status || 'Inactivo';
    schedulerHealth.value.ultimaEjecucion = data.ultima_ejecucion ?? schedulerHealth.value.ultimaEjecucion;
    schedulerHealth.value.ultimoError = data.ultimo_error ?? schedulerHealth.value.ultimoError;
    schedulerHealth.value.verificado = true;
  } catch {
    schedulerHealth.value.estadoClase = 'offline';
    schedulerHealth.value.etiqueta = 'Error de conexión';
    schedulerHealth.value.verificado = true;
  } finally {
    schedulerHealth.value.cargando = false;
  }
}

async function ejecutarSchedulerAhora(): Promise<void> {
  ejecutandoAhora.value = true;
  scheduler.value.msg = '';
  try {
    const res = await dispararSchedulerCromo();
    scheduler.value.msg = `Corrida iniciada (id ${res.corrida_id}). Mirá "Histórico de corridas" para seguirla.`;
    scheduler.value.error = false;
    await cargarHistorico();
  } catch (err: unknown) {
    scheduler.value.msg = err instanceof Error ? err.message : 'No se pudo disparar la ejecución manual.';
    scheduler.value.error = true;
  } finally {
    ejecutandoAhora.value = false;
  }
}

onMounted(() => {
  cargarHistorico();
  cargarConfigScheduler();
  verificarSaludScheduler();
});

onUnmounted(() => {
  cerrarStream();
});
</script>

<style scoped>
.admin-ingesta {
  display: grid;
  gap: var(--space-3);
}

.ingesta-card {
  display: grid;
  gap: var(--space-3);
}

.ingesta-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.ingesta-card__header h2 {
  margin: 0;
}

.ingesta-card__chip {
  font-size: 0.75rem;
  color: var(--color-accent-200);
  background: color-mix(in srgb, var(--color-accent) 22%, transparent);
  border: 1px solid color-mix(in srgb, var(--color-accent) 45%, transparent);
  border-radius: var(--radius-pill);
  padding: 2px 10px;
  white-space: nowrap;
}

.ingesta-card__chip--info {
  color: var(--color-accent-200);
  background: color-mix(in srgb, var(--color-accent) 22%, transparent);
  border-color: color-mix(in srgb, var(--color-accent) 45%, transparent);
}

.ingesta-card__chip--ok {
  color: var(--success);
  background: color-mix(in srgb, var(--success) 15%, transparent);
  border-color: color-mix(in srgb, var(--success) 40%, transparent);
}

.ingesta-card__chip--warn {
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 25%, transparent);
  border-color: color-mix(in srgb, var(--warning) 55%, transparent);
}

.ingesta-card__chip--err {
  color: var(--error);
  background: color-mix(in srgb, var(--error) 18%, transparent);
  border-color: color-mix(in srgb, var(--error) 45%, transparent);
}

.clases-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 8px;
}

.clase-check {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.85rem;
  font-weight: 400;
  margin: 0 !important;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface-2);
  cursor: pointer;
}

.clase-check input {
  width: auto !important;
  margin: 0 !important;
}

.clase-check__nota {
  font-size: 0.72rem;
  color: var(--muted);
}

.clase-check--excluida {
  opacity: 0.55;
  cursor: not-allowed;
}

.fase-actual {
  color: var(--muted);
  font-size: 0.9rem;
  margin: 0;
}

.progress-wrap {
  display: grid;
  gap: 8px;
}

.progress-track {
  height: 12px;
  border-radius: 999px;
  background: var(--color-bg);
  border: 1px solid var(--color-divider);
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--color-accent-700), var(--color-accent) 60%, var(--color-accent-300));
  box-shadow: 0 0 16px color-mix(in srgb, var(--color-accent) 50%, transparent);
  transition: width 0.2s ease;
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.82rem;
  color: var(--color-neutral-400);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: var(--space-2);
  margin: 0;
}

.summary-grid div {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 12px;
  background: var(--color-bg);
}

.summary-grid dt {
  color: var(--muted);
  font-size: 0.78rem;
}

.summary-grid dd {
  font-size: 1.4rem;
  font-weight: 700;
  margin: 0;
}

.dd--warn {
  color: var(--warning);
}

.dd--err {
  color: var(--error);
}

.errores-detalle {
  font-size: 0.83rem;
  color: var(--muted);
}

.errores-detalle summary {
  cursor: pointer;
  color: var(--error);
  margin-bottom: 8px;
}

.errores-list,
.eventos-list {
  padding-left: 18px;
  margin: 0;
  display: grid;
  gap: 6px;
  max-height: 320px;
  overflow-y: auto;
}

.errores-list li {
  color: var(--error);
  word-break: break-word;
  font-size: 0.82rem;
}

.eventos-list {
  padding-left: 0;
  list-style: none;
}

.eventos-list li {
  border-bottom: 1px solid var(--border);
  padding: 6px 0;
  font-size: 0.85rem;
}

.eventos-list__detalle {
  display: block;
  color: var(--muted);
  font-size: 0.78rem;
  word-break: break-word;
}

.btn.subtle {
  background: var(--color-neutral-900);
  border: 1px solid var(--border);
  color: var(--muted);
}

.btn.subtle:hover:not(:disabled) {
  background: var(--color-neutral-800);
  color: var(--text);
}

.tabla-historico {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.85rem;
}

.tabla-historico th {
  text-align: left;
  color: var(--muted);
  font-weight: 500;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
}

.tabla-historico td {
  padding: 6px 10px;
  border-bottom: 1px solid var(--color-divider);
}

.tabla-historico__fila {
  cursor: pointer;
  transition: background 0.15s;
}

.tabla-historico__fila:hover {
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
}

/* ─── Modal de detalle ──────────────────────────────────────────────────── */
.detalle-modal {
  width: min(560px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.detalle-modal::backdrop {
  background: rgba(4, 8, 14, 0.82);
  backdrop-filter: blur(10px);
}

.modal-content {
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: 18px;
  padding: 28px;
  display: grid;
  gap: 16px;
  max-height: 80vh;
  overflow-y: auto;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.modal-header strong {
  font-size: 1.05rem;
}

.close-btn {
  background: none;
  border: none;
  color: var(--muted);
  font-size: 1.4rem;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
  transition: color 0.15s;
}

.close-btn:hover {
  color: var(--text);
}
</style>
