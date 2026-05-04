<!--
  Nombre de archivo: SlaView.vue
  Ubicación de archivo: web/frontend/src/views/SlaView.vue
  Descripción: Vista de Informe SLA — migrada desde sla.html + sla.js, usable como tab o ruta
-->
<template>
  <div class="sla-wrapper">
    <div class="sla-form stack">
      <h1>Informe SLA</h1>
      <div
        class="dropzone"
        :class="{ disabled: useDb, drag: isDrag }"
        :aria-disabled="useDb"
        @click="!useDb && fileEl?.click()"
        @dragover.prevent="!useDb && (isDrag = true)"
        @dragleave="isDrag = false"
        @drop.prevent="handleDrop"
      >
        <input ref="fileEl" type="file" accept=".xlsx" multiple hidden @change="onFileChange" />
        <span>{{ dropLabel }}</span>
      </div>
      <div class="form-grid">
        <div class="field">
          <label class="form-label" for="sla-mes">Mes</label>
          <input id="sla-mes" v-model.number="mes" type="number" min="1" max="12" required />
        </div>
        <div class="field">
          <label class="form-label" for="sla-anio">Año</label>
          <input id="sla-anio" v-model.number="anio" type="number" min="2000" max="2100" required />
        </div>
      </div>
      <label class="checkbox">
        <input v-model="pdfEnabled" type="checkbox" /> Generar PDF si LibreOffice está disponible
      </label>
      <label class="checkbox">
        <input v-model="useDb" type="checkbox" /> Usar reclamos desde la base de datos (ignora archivo)
      </label>
      <div :class="['result-box', flashClass]" role="status" aria-live="polite">{{ flashText }}</div>
      <div class="sla-results">
        <a
          v-for="(href, kind) in reportPaths"
          :key="kind"
          :href="href"
          target="_blank"
          rel="noopener"
          class="btn subtle"
        >{{ String(kind).toUpperCase() }}</a>
      </div>
      <div class="sla-actions">
        <button type="button" class="btn primary" :disabled="loading" @click="generate">Generar informe</button>
        <RouterLink class="btn subtle" to="/reports-history" target="_blank">Carpeta de reportes</RouterLink>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { useSession } from '../composables/useSession';

const { csrf } = useSession();
const mes = ref(new Date().getMonth() + 1);
const anio = ref(new Date().getFullYear());
const pdfEnabled = ref(false);
const useDb = ref(false);
const isDrag = ref(false);
const loading = ref(false);
const flashText = ref('Subí ambos archivos Excel o activá "Usar base" y completá el período.');
const flashClass = ref('muted');
const reportPaths = ref<Record<string, string>>({});
const fileEl = ref<HTMLInputElement | null>(null);
let selectedFiles: File[] = [];

const dropLabel = computed(() => {
  if (useDb.value) return 'Usar base de datos (archivo innecesario)';
  if (selectedFiles.length === 0) return 'Adjuntá "Servicios Fuera de SLA.xlsx" y "Reclamos SLA.xlsx"';
  if (selectedFiles.length === 1) return `Falta el segundo archivo (actual: ${selectedFiles[0].name})`;
  return `${selectedFiles[0].name} + ${selectedFiles[1].name}`;
});

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  selectedFiles = Array.from(input.files ?? []);
  reportPaths.value = {};
}

function handleDrop(e: DragEvent) {
  isDrag.value = false;
  if (useDb.value) return;
  selectedFiles = Array.from(e.dataTransfer?.files ?? []);
  reportPaths.value = {};
}

function setFlash(text: string, cls: string) {
  flashText.value = text;
  flashClass.value = cls;
}

async function generate() {
  reportPaths.value = {};
  if (!useDb.value && selectedFiles.length !== 2) {
    setFlash('Debés adjuntar dos archivos: Servicios Fuera de SLA y Reclamos SLA.', 'error');
    return;
  }
  if (!mes.value || !anio.value) {
    setFlash('Indicá mes y año válidos.', 'error');
    return;
  }
  setFlash('Procesando informe...', 'info');
  loading.value = true;
  const fd = new FormData();
  fd.append('mes', String(mes.value));
  fd.append('anio', String(anio.value));
  fd.append('periodo_mes', String(mes.value));
  fd.append('periodo_anio', String(anio.value));
  fd.append('pdf_enabled', pdfEnabled.value ? 'true' : 'false');
  fd.append('use_db', useDb.value ? 'true' : 'false');
  if (!useDb.value) {
    selectedFiles.forEach(f => fd.append('files', f, f.name));
  }
  fd.append('csrf_token', csrf());
  try {
    const res = await fetch('/api/reports/sla', { method: 'POST', body: fd, credentials: 'include' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) {
      const msg = data.error ?? data.detail ?? data.message ?? `Error ${res.status}`;
      throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
    }
    setFlash(data.message ?? 'Informe SLA generado correctamente.', 'success');
    reportPaths.value = data.report_paths ?? {};
  } catch (e: unknown) {
    setFlash(`Error: ${e instanceof Error ? e.message : String(e)}`, 'error');
  } finally {
    loading.value = false;
  }
}
</script>
