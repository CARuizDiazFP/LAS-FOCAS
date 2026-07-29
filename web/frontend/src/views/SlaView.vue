<!--
  Nombre de archivo: SlaView.vue
  Ubicación de archivo: web/frontend/src/views/SlaView.vue
  Descripción: Vista de Informe SLA — migrada desde sla.html + sla.js, usable como tab o ruta
-->
<template>
  <section class="sla-view">
    <header class="sla-view__header">
      <span class="sla-view__kicker">Reportes</span>
      <h1>Informe SLA</h1>
      <p class="sla-view__context">
        Definí el período de corte, seleccioná los archivos fuente o trabajá con datos de base, y generá informes
        SLA operativos con salida descargable. Si LibreOffice está disponible también podés emitir la versión PDF.
      </p>
    </header>

    <hr class="noc-rule" />

    <div class="sla-view__body">
      <div class="sla-view__column">
        <div
          class="sla-view__dropzone"
          :class="{ disabled: useDb, drag: isDrag }"
          :aria-disabled="useDb"
          @click="!useDb && fileEl?.click()"
          @dragover.prevent="!useDb && (isDrag = true)"
          @dragleave="isDrag = false"
          @drop.prevent="handleDrop"
        >
          <input ref="fileEl" type="file" accept=".xlsx" multiple hidden @change="onFileChange" />
          <i class="ph ph-file-xls" aria-hidden="true"></i>
          <strong>{{ dropLabel }}</strong>
          <span class="sla-view__dropzone-hint">Servicios Fuera de SLA.xlsx + Reclamos SLA.xlsx</span>
        </div>

        <div v-if="selectedFiles.length > 0" class="sla-view__files">
          <span v-for="file in selectedFiles" :key="file.name" class="sla-view__file-chip">
            <i class="ph ph-check-circle" aria-hidden="true"></i>
            {{ file.name }}
          </span>
        </div>

        <div class="sla-view__period">
          <div class="sla-view__field">
            <label for="sla-mes">Mes</label>
            <input id="sla-mes" v-model.number="mes" type="number" min="1" max="12" required />
          </div>
          <div class="sla-view__field">
            <label for="sla-anio">Año</label>
            <input id="sla-anio" v-model.number="anio" type="number" min="2000" max="2100" required />
          </div>
        </div>

        <label class="sla-view__checkbox">
          <input v-model="pdfEnabled" type="checkbox" />
          <span class="sla-view__checkbox-box"><i class="ph ph-check" aria-hidden="true"></i></span>
          Generar PDF si LibreOffice está disponible
        </label>
        <label class="sla-view__checkbox">
          <input v-model="useDb" type="checkbox" />
          <span class="sla-view__checkbox-box"><i class="ph ph-check" aria-hidden="true"></i></span>
          Usar reclamos desde la base de datos (ignora archivo)
        </label>

        <div class="sla-view__actions">
          <button type="button" class="btn primary" :disabled="loading" @click="generate">
            <i class="ph ph-play" aria-hidden="true"></i>
            Generar informe
          </button>
          <RouterLink class="btn subtle" to="/reports-history" target="_blank">Carpeta de reportes</RouterLink>
        </div>
      </div>

      <div class="sla-view__column">
        <div v-if="Object.keys(reportPaths).length > 0" class="sla-view__card">
          <header>
            <i class="ph ph-check-circle" aria-hidden="true"></i>
            <h2>Salidas generadas</h2>
          </header>
          <div class="sla-view__hairline"></div>
          <div class="sla-view__outputs">
            <a
              v-for="(href, kind) in reportPaths"
              :key="kind"
              :href="href"
              target="_blank"
              rel="noopener"
              class="sla-view__output-link"
            >{{ String(kind).toUpperCase() }}</a>
          </div>
        </div>

        <div class="sla-view__status-box" :class="`is-${flashClass}`" role="status" aria-live="polite">
          <span class="sla-view__status-label">Estado</span>
          <p>{{ flashText }}</p>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useSla } from '../composables/useSla';

const mes = ref(new Date().getMonth() + 1);
const anio = ref(new Date().getFullYear());
const pdfEnabled = ref(false);
const useDb = ref(false);
const isDrag = ref(false);
const fileEl = ref<HTMLInputElement | null>(null);
const {
  selectedFiles,
  reportPaths,
  loading,
  flashText,
  flashClass,
  setSelectedFiles,
  generate: generateSla,
} = useSla();

const dropLabel = computed(() => {
  if (useDb.value) return 'Usar base de datos (archivo innecesario)';
  if (selectedFiles.value.length === 0) return 'Adjuntá los dos archivos Excel';
  if (selectedFiles.value.length === 1) return `Falta el segundo archivo (actual: ${selectedFiles.value[0].name})`;
  return `${selectedFiles.value[0].name} + ${selectedFiles.value[1].name}`;
});

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  setSelectedFiles(Array.from(input.files ?? []));
}

function handleDrop(e: DragEvent) {
  isDrag.value = false;
  if (useDb.value) return;
  setSelectedFiles(Array.from(e.dataTransfer?.files ?? []));
}

async function generate() {
  await generateSla({
    mes: mes.value,
    anio: anio.value,
    periodo_mes: mes.value,
    periodo_anio: anio.value,
    pdf_enabled: pdfEnabled.value,
    use_db: useDb.value,
    files: selectedFiles.value,
  });
}
</script>

<style scoped>
.sla-view {
  padding-bottom: 26px;
}

.sla-view__header {
  padding: 22px 26px 0;
}

.sla-view__kicker {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.sla-view__header h1 {
  font-size: 27px;
  margin: 3px 0 0;
}

.sla-view__context {
  max-width: 620px;
  margin: 8px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: color-mix(in srgb, var(--color-text) 52%, transparent);
  text-wrap: pretty;
}

.sla-view__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 22px;
  padding: 20px 26px 26px;
}

.sla-view__column {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.sla-view__dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 34px 22px;
  border: 1px dashed var(--color-neutral-700);
  border-radius: var(--radius-md);
  text-align: center;
  cursor: pointer;
}

.sla-view__dropzone i {
  font-size: 26px;
  color: var(--color-neutral-500);
}

.sla-view__dropzone strong {
  font-family: var(--font-heading);
  font-size: 14px;
  font-weight: 500;
}

.sla-view__dropzone-hint {
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 50%, transparent);
}

.sla-view__dropzone:hover,
.sla-view__dropzone.drag {
  border-color: var(--color-accent);
}

.sla-view__dropzone.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.sla-view__files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sla-view__file-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 4px;
  background: var(--color-surface);
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 72%, transparent);
}

.sla-view__file-chip i {
  font-size: 13px;
  color: var(--color-state-ok);
}

.sla-view__period {
  display: grid;
  grid-template-columns: 120px 120px;
  gap: 11px;
}

.sla-view__field label {
  display: block;
  margin-bottom: 5px;
  font-size: 12px;
  color: color-mix(in srgb, var(--color-text) 70%, transparent);
}

.sla-view__field input {
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  font-size: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
}

.sla-view__checkbox {
  display: flex;
  align-items: center;
  gap: 9px;
  font-size: 13px;
  cursor: pointer;
}

.sla-view__checkbox input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
}

.sla-view__checkbox-box {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  flex: none;
  border-radius: 4px;
  border: 1px solid var(--color-divider);
}

.sla-view__checkbox-box i {
  font-size: 11px;
  color: var(--color-accent);
  opacity: 0;
}

.sla-view__checkbox input:checked + .sla-view__checkbox-box {
  border-color: var(--color-accent);
  background: color-mix(in srgb, var(--color-accent) 20%, transparent);
}

.sla-view__checkbox input:checked + .sla-view__checkbox-box i {
  opacity: 1;
}

.sla-view__checkbox input:focus-visible + .sla-view__checkbox-box {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}

.sla-view__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.sla-view__actions .btn {
  min-height: 38px;
}

.sla-view__card {
  display: flex;
  flex-direction: column;
  gap: 9px;
  padding: 14px;
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
}

.sla-view__card header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sla-view__card header i {
  font-size: 16px;
  color: var(--color-state-ok);
}

.sla-view__card h2 {
  margin: 0;
  font-size: 15px;
}

.sla-view__hairline {
  height: 1px;
  background: var(--color-divider);
}

.sla-view__outputs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.sla-view__output-link {
  font-size: 11px;
  padding: 3px 9px;
  border: 1px solid var(--color-divider);
  border-radius: 4px;
  color: color-mix(in srgb, var(--color-text) 72%, transparent);
  text-decoration: none;
}

.sla-view__output-link:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.sla-view__status-box {
  padding: 12px 14px;
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-neutral-800);
}

.sla-view__status-label {
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-neutral-500);
}

.sla-view__status-box p {
  margin: 4px 0 0;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 62%, transparent);
}

.sla-view__status-box.is-success {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-ok) 45%, transparent);
}

.sla-view__status-box.is-error {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--color-state-error) 45%, transparent);
}

.sla-view__status-box.is-error p {
  color: var(--color-state-error);
}

@media (max-width: 1100px) {
  .sla-view__body {
    grid-template-columns: 1fr;
  }
}
</style>
