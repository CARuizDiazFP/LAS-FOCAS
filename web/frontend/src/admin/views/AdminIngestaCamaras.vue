<!--
  Nombre de archivo: AdminIngestaCamaras.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminIngestaCamaras.vue
  Descripción: Vista admin para la ingesta masiva de cámaras desde Excel con modal de motivo de baneo
-->
<template>
  <section class="admin-ingesta">
    <AdminPageHeader
      kicker="Ingesta · Cámaras"
      title="Ingesta de Cámaras"
      subtitle="Carga masiva de cámaras desde Excel y aplicación de baneo administrativo."
    />

    <article class="card ingesta-card">
      <header class="ingesta-card__header">
        <h2>Cámaras Críticas</h2>
        <span class="ingesta-card__chip ingesta-card__chip--warn">Baneo Masivo</span>
      </header>

      <label class="ingesta-card__dropzone" :class="{ 'ingesta-card__dropzone--disabled': uploading }" for="file-input-camaras">
        <span>Seleccioná el archivo de Cámaras Críticas</span>
        <small>Formatos soportados: .xlsx, .xlsm · Alias en columna B</small>
      </label>
      <input
        id="file-input-camaras"
        ref="fileInput"
        type="file"
        accept=".xlsx,.xlsm"
        hidden
        :disabled="uploading"
        @change="onSelectFile"
      />

      <div v-if="uploading || progress > 0" class="progress-wrap" role="status" aria-live="polite">
        <div class="progress-track">
          <div class="progress-bar progress-bar--warn" :style="{ width: `${progress}%` }"></div>
        </div>
        <div class="progress-meta">
          <span>{{ progress }}%</span>
          <span>{{ statusText }}</span>
        </div>
      </div>

      <p v-if="feedback" :class="['msg', feedbackType === 'ok' ? 'ok' : 'err', 'visible']">{{ feedback }}</p>

      <dl v-if="summary" class="summary-grid">
        <div>
          <dt>Leídos</dt>
          <dd>{{ summary.total_leidos }}</dd>
        </div>
        <div>
          <dt>Grupos baneados</dt>
          <dd class="dd--warn">{{ summary.grupos_baneados }}</dd>
        </div>
        <div>
          <dt>Ya baneados</dt>
          <dd>{{ summary.grupos_ya_baneados }}</dd>
        </div>
        <div v-if="summary.sin_match.length > 0">
          <dt>Sin match</dt>
          <dd class="dd--err">{{ summary.sin_match.length }}</dd>
        </div>
        <div v-if="summary.errores.length > 0">
          <dt>Errores</dt>
          <dd class="dd--err">{{ summary.errores.length }}</dd>
        </div>
      </dl>

      <details v-if="summary && summary.errores.length > 0" class="errores-detalle">
        <summary>Ver errores ({{ summary.errores.length }})</summary>
        <ul class="errores-list">
          <li v-for="(err, i) in summary.errores" :key="i">{{ err }}</li>
        </ul>
      </details>
    </article>

    <article v-if="sinMatchPendientes.length > 0" class="card">
      <header class="ingesta-card__header">
        <h2>Revisor Manual</h2>
        <span class="ingesta-card__chip ingesta-card__chip--warn">{{ sinMatchPendientes.length }} pendientes</span>
      </header>
      <p class="revisor-hint">
        Nombres del Excel que no matchearon contra el inventario. Asocialos a una Cámara/Botella existente
        (crea un alias para que futuros Excel con el mismo texto matcheen solos) o descartalos de esta vista.
      </p>

      <p v-if="revisorFeedback" :class="['msg', revisorFeedbackType === 'ok' ? 'ok' : 'err', 'visible']">
        {{ revisorFeedback }}
      </p>

      <table class="revisor-tabla">
        <thead>
          <tr>
            <th class="revisor-tabla__check">
              <input
                type="checkbox"
                :checked="todosSeleccionados"
                aria-label="Seleccionar todos"
                @change="toggleTodos"
              />
            </th>
            <th>Nombre original</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="caso in sinMatchPendientes" :key="caso.id">
            <td class="revisor-tabla__check">
              <input
                type="checkbox"
                :checked="seleccionados.has(caso.id)"
                @change="toggleSeleccion(caso.id)"
              />
            </td>
            <td>{{ caso.texto_original }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="seleccionados.size > 0" class="revisor-acciones">
        <span class="revisor-acciones__count">{{ seleccionados.size }} seleccionado(s)</span>
        <button class="btn subtle" type="button" @click="abrirDescartarMasivo">Descartar seleccionados</button>
        <button class="btn primary" type="button" @click="abrirAsociarSinMatch">Asociar seleccionados…</button>
      </div>
    </article>

    <ModalConfirmarAccionMasiva
      :open="modalDescartarOpen"
      titulo="Descartar de la vista"
      :mensaje="mensajeDescartarMasivo"
      :confirmando="descartando"
      :error="descartarError"
      :resultado="descartarResultado"
      @close="cerrarDescartarMasivo"
      @confirm="confirmarDescartarMasivo"
    />

    <ModalAsociarSinMatch
      :open="modalAsociarOpen"
      :casos="casosParaAsociar"
      :motivo-sugerido="motivoBaneo"
      @close="modalAsociarOpen = false"
      @asociada="onAsociada"
    />

    <!-- Modal de motivo de baneo -->
    <dialog ref="dialogEl" class="motivo-modal" @click.self="cancelarModal">
      <div class="modal-content">
        <div class="modal-header">
          <strong>Confirmar Baneo Masivo</strong>
          <button class="close-btn" type="button" aria-label="Cerrar" @click="cancelarModal">×</button>
        </div>

        <p class="modal-desc">
          Se leerán los aliases de la columna B de
          <strong>{{ archivoSeleccionado?.name }}</strong>
          y se cambiará el estado de todas las cámaras a <span class="badge-baneada">BANEADA</span>.
        </p>

        <label class="modal-label" for="motivo-input">Motivo del baneo <span class="required">*</span></label>
        <textarea
          id="motivo-input"
          v-model="motivoBaneo"
          class="modal-textarea"
          rows="3"
          placeholder="Ej: Corte programado en zona norte — OT-2026-07-27"
          maxlength="500"
          :disabled="confirmando"
        ></textarea>
        <p v-if="motivoError" class="modal-error">{{ motivoError }}</p>

        <div class="modal-actions">
          <button class="btn primary" type="button" :disabled="confirmando" @click="confirmarBaneo">
            {{ confirmando ? 'Procesando…' : 'Confirmar baneo' }}
          </button>
          <button class="btn subtle" type="button" :disabled="confirmando" @click="cancelarModal">
            Cancelar
          </button>
        </div>
      </div>
    </dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import AdminPageHeader from '../components/AdminPageHeader.vue';
import ModalConfirmarAccionMasiva from '../../components/infra/ModalConfirmarAccionMasiva.vue';
import ModalAsociarSinMatch from '../components/ModalAsociarSinMatch.vue';
import { ingestCamarasFile, type AsociarSinMatchResponse, type IngestCamarasResponse } from '../../api/camaras';
import { getIngresosSinMatch, marcarRevisadoMasivo, type IngresoSinMatch } from '../api/admin';

const fileInput = ref<HTMLInputElement | null>(null);
const dialogEl = ref<HTMLDialogElement | null>(null);

const archivoSeleccionado = ref<File | null>(null);
const motivoBaneo = ref('');
const motivoError = ref('');
const confirmando = ref(false);

const uploading = ref(false);
const progress = ref(0);
const statusText = ref('Listo para cargar');
const feedback = ref('');
const feedbackType = ref<'ok' | 'err'>('ok');
const summary = ref<IngestCamarasResponse | null>(null);

// ─── Revisor Manual: nombres del Excel que no matchearon contra el inventario ───
const sinMatchPendientes = ref<IngresoSinMatch[]>([]);
const seleccionados = ref<Set<number>>(new Set());
const revisorFeedback = ref('');
const revisorFeedbackType = ref<'ok' | 'err'>('ok');

const todosSeleccionados = computed(
  () => sinMatchPendientes.value.length > 0 && seleccionados.value.size === sinMatchPendientes.value.length,
);

function toggleSeleccion(id: number): void {
  const next = new Set(seleccionados.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  seleccionados.value = next;
}

function toggleTodos(): void {
  seleccionados.value = todosSeleccionados.value
    ? new Set()
    : new Set(sinMatchPendientes.value.map((caso) => caso.id));
}

async function cargarSinMatchPendientes(): Promise<void> {
  sinMatchPendientes.value = await getIngresosSinMatch(false, 'excel_camaras');
  const idsVigentes = new Set(sinMatchPendientes.value.map((caso) => caso.id));
  seleccionados.value = new Set([...seleccionados.value].filter((id) => idsVigentes.has(id)));
}

onMounted(() => {
  void cargarSinMatchPendientes();
});

// ─── Descarte masivo — no borra nada real, sólo marca revisado=true ────────
const modalDescartarOpen = ref(false);
const descartando = ref(false);
const descartarError = ref('');
const descartarResultado = ref<string | null>(null);

const mensajeDescartarMasivo = computed(
  () =>
    `Se van a marcar ${seleccionados.value.size} nombre(s) como revisados y desaparecen de esta lista. ` +
    'La fila queda en la base para poder mejorar el regex de matching a futuro — no se borra ningún dato real.',
);

function abrirDescartarMasivo(): void {
  descartarError.value = '';
  descartarResultado.value = null;
  modalDescartarOpen.value = true;
}

function cerrarDescartarMasivo(): void {
  modalDescartarOpen.value = false;
}

async function confirmarDescartarMasivo(): Promise<void> {
  descartando.value = true;
  descartarError.value = '';
  try {
    await marcarRevisadoMasivo([...seleccionados.value]);
    seleccionados.value = new Set();
    modalDescartarOpen.value = false;
    await cargarSinMatchPendientes();
  } catch (err: unknown) {
    descartarError.value = err instanceof Error ? err.message : 'No se pudo descartar la selección';
  } finally {
    descartando.value = false;
  }
}

// ─── Asociación manual a una Cámara/Botella existente ──────────────────────
const modalAsociarOpen = ref(false);

const casosParaAsociar = computed(() =>
  sinMatchPendientes.value
    .filter((caso) => seleccionados.value.has(caso.id))
    .map((caso) => ({ caso_id: caso.id, nombre: caso.texto_original })),
);

function abrirAsociarSinMatch(): void {
  modalAsociarOpen.value = true;
}

async function onAsociada(resultado: AsociarSinMatchResponse): Promise<void> {
  modalAsociarOpen.value = false;
  seleccionados.value = new Set();
  if (resultado.conflictos.length > 0) {
    const nombres = resultado.conflictos.map((c) => c.nombre).join(', ');
    revisorFeedbackType.value = 'err';
    revisorFeedback.value = `${resultado.conflictos.length} nombre(s) no se asociaron porque ya tienen un alias hacia otra Cámara: ${nombres}. Siguen pendientes.`;
  } else if (resultado.error) {
    revisorFeedbackType.value = 'err';
    revisorFeedback.value = `Asociación aplicada con una advertencia: ${resultado.error}`;
  } else {
    revisorFeedbackType.value = 'ok';
    revisorFeedback.value = `Asociado a "${resultado.camara_nombre}" (${resultado.alias_creados} alias nuevo(s), ${resultado.casos_marcados} caso(s) marcado(s)).`;
  }
  await cargarSinMatchPendientes();
}

function onSelectFile(event: Event): void {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;

  archivoSeleccionado.value = file;
  motivoBaneo.value = '';
  motivoError.value = '';
  feedback.value = '';
  summary.value = null;
  progress.value = 0;

  dialogEl.value?.showModal();
}

function cancelarModal(): void {
  if (confirmando.value) return;
  dialogEl.value?.close();
  archivoSeleccionado.value = null;
  motivoBaneo.value = '';
  motivoError.value = '';
  if (fileInput.value) fileInput.value.value = '';
}

async function confirmarBaneo(): Promise<void> {
  const motivo = motivoBaneo.value.trim();
  if (!motivo) {
    motivoError.value = 'El motivo es obligatorio';
    return;
  }
  motivoError.value = '';

  const file = archivoSeleccionado.value;
  if (!file) return;

  confirmando.value = true;
  dialogEl.value?.close();

  uploading.value = true;
  progress.value = 0;
  statusText.value = `Subiendo ${file.name}`;

  try {
    const result = await ingestCamarasFile(file, motivo, (percent) => {
      progress.value = percent;
    });

    summary.value = result;
    progress.value = 100;
    statusText.value = 'Ingesta completada';
    feedbackType.value = 'ok';
    feedback.value = `Proceso finalizado: ${result.grupos_baneados} grupo(s) baneado(s), ${result.grupos_ya_baneados} ya baneado(s), ${result.sin_match.length} sin match.`;
    await cargarSinMatchPendientes();
  } catch (err: unknown) {
    feedbackType.value = 'err';
    feedback.value = err instanceof Error ? err.message : 'No se pudo completar la ingesta';
    statusText.value = 'Error de ingesta';
  } finally {
    uploading.value = false;
    confirmando.value = false;
    archivoSeleccionado.value = null;
    if (fileInput.value) fileInput.value.value = '';
  }
}
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
}

.ingesta-card__chip--warn {
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 25%, transparent);
  border-color: color-mix(in srgb, var(--warning) 55%, transparent);
}

.ingesta-card__dropzone {
  border: 1px dashed color-mix(in srgb, var(--warning) 55%, transparent);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--warning) 8%, transparent);
  min-height: 110px;
  display: grid;
  place-content: center;
  gap: 6px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.ingesta-card__dropzone:hover:not(.ingesta-card__dropzone--disabled) {
  border-color: color-mix(in srgb, var(--warning) 90%, transparent);
  background: color-mix(in srgb, var(--warning) 15%, transparent);
}

.ingesta-card__dropzone--disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.ingesta-card__dropzone span {
  font-weight: 600;
}

.ingesta-card__dropzone small {
  color: var(--muted);
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

.progress-bar--warn {
  background: linear-gradient(90deg, color-mix(in srgb, var(--warning) 70%, black), var(--warning) 60%, color-mix(in srgb, var(--warning) 70%, white));
  box-shadow: 0 0 16px color-mix(in srgb, var(--warning) 50%, transparent);
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.82rem;
  color: var(--color-neutral-400);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
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

.errores-list {
  padding-left: 18px;
  margin: 0;
  display: grid;
  gap: 4px;
}

.errores-list li {
  color: var(--error);
  word-break: break-word;
}

/* ─── Modal ─────────────────────────────────────────────────────────────── */
.motivo-modal {
  width: min(520px, calc(100vw - 32px));
  background: transparent;
  border: none;
  padding: 0;
}

.motivo-modal::backdrop {
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

.modal-desc {
  font-size: 0.88rem;
  color: var(--muted);
  margin: 0;
  line-height: 1.55;
}

.badge-baneada {
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--warning);
  background: color-mix(in srgb, var(--warning) 30%, transparent);
  border: 1px solid color-mix(in srgb, var(--warning) 60%, transparent);
  border-radius: var(--radius-pill);
  padding: 1px 8px;
}

.modal-label {
  font-size: 0.875rem;
  color: var(--muted);
  margin: 0;
}

.required {
  color: var(--error);
}

.modal-textarea {
  width: 100%;
  background: var(--color-bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-size: 0.9rem;
  padding: 10px 12px;
  resize: vertical;
  box-sizing: border-box;
  font-family: inherit;
  transition: border-color 0.15s;
}

.modal-textarea:focus {
  outline: none;
  border-color: var(--primary);
}

.modal-textarea:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.modal-error {
  font-size: 0.82rem;
  color: var(--error);
  margin: -8px 0 0;
}

.modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
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

/* ─── Revisor Manual ────────────────────────────────────────────────────── */
.revisor-hint {
  font-size: 0.85rem;
  color: var(--muted);
  margin: 0;
  line-height: 1.5;
}

.revisor-tabla {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.88rem;
}

.revisor-tabla th,
.revisor-tabla td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--color-divider);
  text-align: left;
}

.revisor-tabla th {
  color: var(--muted);
  font-size: 0.78rem;
  font-weight: 600;
}

.revisor-tabla__check {
  width: 32px;
}

.revisor-acciones {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.revisor-acciones__count {
  font-size: 0.85rem;
  color: var(--muted);
}
</style>
