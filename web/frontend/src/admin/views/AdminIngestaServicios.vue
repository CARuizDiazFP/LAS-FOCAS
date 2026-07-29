<!--
  Nombre de archivo: AdminIngestaServicios.vue
  Ubicación de archivo: web/frontend/src/admin/views/AdminIngestaServicios.vue
  Descripción: Vista admin para la ingesta del Excel de Servicios SLA con barra de progreso
-->
<template>
  <section class="admin-ingesta">
    <h1>Ingesta de Servicios SLA</h1>
    <p class="section-subtitle">Carga automática del Excel de Servicios SLA.</p>

    <article class="card ingesta-card">
      <header class="ingesta-card__header">
        <h2>Servicios SLA</h2>
        <span class="ingesta-card__chip">Dark Upload</span>
      </header>

      <label class="ingesta-card__dropzone" for="file-input-sla">
        <span>Seleccioná el archivo de Servicios SLA</span>
        <small>Formatos soportados: .xlsx, .xlsm, .csv</small>
      </label>
      <input id="file-input-sla" ref="fileInput" type="file" accept=".xlsx,.xlsm,.csv" hidden @change="onSelectFile" />

      <div v-if="uploading || progress > 0" class="progress-wrap" role="status" aria-live="polite">
        <div class="progress-track">
          <div class="progress-bar" :style="{ width: `${progress}%` }"></div>
        </div>
        <div class="progress-meta">
          <span>{{ progress }}%</span>
          <span>{{ statusText }}</span>
        </div>
      </div>

      <p v-if="feedback" :class="['msg', feedbackType === 'ok' ? 'ok' : 'err', 'visible']">{{ feedback }}</p>

      <dl v-if="summary" class="summary-grid">
        <div>
          <dt>Filas válidas</dt>
          <dd>{{ summary.rows_ok }}</dd>
        </div>
        <div>
          <dt>Filas inválidas</dt>
          <dd>{{ summary.rows_bad }}</dd>
        </div>
        <div>
          <dt>Insertados</dt>
          <dd>{{ summary.inserted }}</dd>
        </div>
        <div>
          <dt>Actualizados</dt>
          <dd>{{ summary.updated }}</dd>
        </div>
      </dl>
    </article>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue';

import { ingestServiciosFile, type IngestServiciosResponse } from '../../api/servicios';

const fileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const progress = ref(0);
const statusText = ref('Listo para cargar');
const feedback = ref('');
const feedbackType = ref<'ok' | 'err'>('ok');
const summary = ref<IngestServiciosResponse | null>(null);

async function onSelectFile(event: Event): Promise<void> {
  const target = event.target as HTMLInputElement;
  const file = target.files?.[0];
  if (!file) return;

  feedback.value = '';
  summary.value = null;
  uploading.value = true;
  progress.value = 0;
  statusText.value = `Subiendo ${file.name}`;

  try {
    const result = await ingestServiciosFile(file, (percent) => {
      progress.value = percent;
    });

    summary.value = result;
    progress.value = 100;
    statusText.value = 'Ingesta completada';
    feedbackType.value = 'ok';
    feedback.value = `Proceso finalizado: ${result.inserted} insertados, ${result.updated} actualizados.`;
  } catch (err: unknown) {
    feedbackType.value = 'err';
    feedback.value = err instanceof Error ? err.message : 'No se pudo completar la ingesta';
    statusText.value = 'Error de ingesta';
  } finally {
    uploading.value = false;
    if (target) target.value = '';
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

.ingesta-card__dropzone {
  border: 1px dashed rgba(96, 165, 250, 0.6);
  border-radius: var(--radius-lg);
  background: rgba(30, 41, 59, 0.45);
  min-height: 110px;
  display: grid;
  place-content: center;
  gap: 6px;
  text-align: center;
  cursor: pointer;
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
</style>
