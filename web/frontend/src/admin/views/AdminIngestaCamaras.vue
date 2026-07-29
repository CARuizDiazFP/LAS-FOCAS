<!--
  Nombre de archivo: AdminIngestaCamaras.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminIngestaCamaras.vue
  Descripción: Vista admin para la ingesta masiva de cámaras desde Excel con modal de motivo de baneo
-->
<template>
  <section class="admin-ingesta">
    <h1>Ingesta de Cámaras</h1>
    <p class="section-subtitle">Carga masiva de cámaras desde Excel y aplicación de baneo administrativo.</p>

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
          <dt>Creadas</dt>
          <dd>{{ summary.creadas }}</dd>
        </div>
        <div>
          <dt>Preexistentes</dt>
          <dd>{{ summary.preexistentes }}</dd>
        </div>
        <div>
          <dt>Baneadas</dt>
          <dd class="dd--warn">{{ summary.baneadas }}</dd>
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
import { ref } from 'vue';

import { ingestCamarasFile, type IngestCamarasResponse } from '../../api/camaras';

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
    feedback.value = `Proceso finalizado: ${result.creadas} cámaras creadas, ${result.preexistentes} preexistentes, ${result.baneadas} baneadas.`;
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
}

.ingesta-card__chip--warn {
  color: #fef3c7;
  background: rgba(217, 119, 6, 0.25);
  border-color: rgba(217, 119, 6, 0.55);
}

.ingesta-card__dropzone {
  border: 1px dashed rgba(251, 191, 36, 0.55);
  border-radius: var(--radius-lg);
  background: rgba(30, 41, 59, 0.45);
  min-height: 110px;
  display: grid;
  place-content: center;
  gap: 6px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.ingesta-card__dropzone:hover:not(.ingesta-card__dropzone--disabled) {
  border-color: rgba(251, 191, 36, 0.9);
  background: rgba(30, 41, 59, 0.65);
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

.progress-bar--warn {
  background: linear-gradient(90deg, #d97706, #f59e0b 60%, #fbbf24);
  box-shadow: 0 0 16px rgba(251, 191, 36, 0.5);
}

.progress-meta {
  display: flex;
  justify-content: space-between;
  font-size: 0.82rem;
  color: #bfdbfe;
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

.errores-list {
  padding-left: 18px;
  margin: 0;
  display: grid;
  gap: 4px;
}

.errores-list li {
  color: #fca5a5;
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
  background: linear-gradient(180deg, rgba(17, 24, 39, 0.98), rgba(9, 14, 23, 0.98));
  border: 1px solid rgba(148, 163, 184, 0.18);
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
  color: #fef3c7;
  background: rgba(217, 119, 6, 0.3);
  border: 1px solid rgba(217, 119, 6, 0.6);
  border-radius: var(--radius-pill);
  padding: 1px 8px;
}

.modal-label {
  font-size: 0.875rem;
  color: var(--muted);
  margin: 0;
}

.required {
  color: #f87171;
}

.modal-textarea {
  width: 100%;
  background: rgba(15, 23, 42, 0.7);
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
  color: #f87171;
  margin: -8px 0 0;
}

.modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
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
</style>
