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

.ingesta-card__dropzone {
  border: 1px dashed color-mix(in srgb, var(--color-accent) 55%, transparent);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--color-accent) 8%, transparent);
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
</style>
