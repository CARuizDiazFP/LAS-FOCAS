<!--
  Nombre de archivo: AdminIngestaCromo.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminIngestaCromo.vue
  Descripción: Vista admin para disparar y seguir en vivo una corrida de ingesta de inventario FO desde Cromo Red
-->
<template>
  <section class="admin-ingesta">
    <h1>Ingesta de Cromo</h1>
    <p class="section-subtitle">
      Trae el inventario de fibra óptica (botellas, cables, tubos, pelos, fusiones) desde Cromo Red.
      Sólo lectura sobre Cromo — nunca escribe ahí.
    </p>

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

import {
  CROMO_CATALOGO_BOTELLAS,
  CROMO_CLASE_EXCLUIDA,
  CROMO_PSIZE_OPCIONES,
  cancelarIngestaCromo,
  iniciarIngestaCromo,
  obtenerDetalleCromo,
  obtenerHistoricoCromo,
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
    const maxPaginas = maxPaginasInput.value.trim() ? Number(maxPaginasInput.value) : null;
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

onMounted(() => {
  cargarHistorico();
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
  background: linear-gradient(180deg, rgba(16, 22, 31, 0.98), rgba(10, 14, 20, 0.96));
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
  color: #dbeafe;
  background: rgba(37, 99, 235, 0.25);
  border: 1px solid rgba(37, 99, 235, 0.55);
  border-radius: var(--radius-pill);
  padding: 2px 10px;
  white-space: nowrap;
}

.ingesta-card__chip--info {
  color: #dbeafe;
  background: rgba(37, 99, 235, 0.25);
  border-color: rgba(37, 99, 235, 0.55);
}

.ingesta-card__chip--ok {
  color: #6ee7b7;
  background: rgba(16, 185, 129, 0.15);
  border-color: rgba(16, 185, 129, 0.4);
}

.ingesta-card__chip--warn {
  color: #fef3c7;
  background: rgba(217, 119, 6, 0.25);
  border-color: rgba(217, 119, 6, 0.55);
}

.ingesta-card__chip--err {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.18);
  border-color: rgba(239, 68, 68, 0.45);
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
  background: #0b1220;
  border: 1px solid #1f2937;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #2563eb, #38bdf8 60%, #22d3ee);
  box-shadow: 0 0 16px rgba(56, 189, 248, 0.5);
  transition: width 0.2s ease;
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.82rem;
  color: #bfdbfe;
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
  background: rgba(15, 23, 42, 0.55);
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
  color: #fbbf24;
}

.dd--err {
  color: #f87171;
}

.errores-detalle {
  font-size: 0.83rem;
  color: var(--muted);
}

.errores-detalle summary {
  cursor: pointer;
  color: #f87171;
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
  color: #fca5a5;
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

.msg {
  padding: 10px 14px;
  border-radius: var(--radius);
  font-size: 0.88rem;
  display: none;
}

.msg.visible {
  display: block;
}

.msg.ok {
  background: rgba(16, 185, 129, 0.12);
  border: 1px solid rgba(16, 185, 129, 0.35);
  color: #6ee7b7;
}

.msg.err {
  background: rgba(239, 68, 68, 0.12);
  border: 1px solid rgba(239, 68, 68, 0.35);
  color: #fca5a5;
}

.btn.subtle {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid var(--border);
  color: var(--muted);
}

.btn.subtle:hover:not(:disabled) {
  background: rgba(30, 41, 59, 0.8);
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
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

.tabla-historico__fila {
  cursor: pointer;
  transition: background 0.15s;
}

.tabla-historico__fila:hover {
  background: rgba(37, 99, 235, 0.1);
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
  background: linear-gradient(180deg, rgba(17, 24, 39, 0.98), rgba(9, 14, 23, 0.98));
  border: 1px solid rgba(148, 163, 184, 0.18);
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
