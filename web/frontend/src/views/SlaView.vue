<!--
  Nombre de archivo: SlaView.vue
  Ubicación de archivo: web/frontend/src/views/SlaView.vue
  Descripción: Vista de Informe SLA — migrada desde sla.html + sla.js, usable como tab o ruta
-->
<template>
  <article class="module-screen sla-wrapper">
    <header class="module-header">
      <div class="module-heading">
        <p class="module-eyebrow">Reportes</p>
        <h1>Informe SLA</h1>
      </div>
    </header>

    <section class="info-card" aria-label="Contexto del submódulo SLA">
      <p>
        Utilice este panel para definir el período de corte, seleccionar los archivos fuente o trabajar con datos
        de base, y generar informes SLA operativos con salida descargable. Si LibreOffice está disponible también
        podrá emitir la versión PDF desde el mismo flujo.
      </p>
    </section>

    <main class="module-content">
      <div class="sla-form stack">
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
    </main>
  </article>
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
  if (selectedFiles.value.length === 0) return 'Adjuntá "Servicios Fuera de SLA.xlsx" y "Reclamos SLA.xlsx"';
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
.module-screen {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.module-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
}

.module-heading h1 {
  margin: 0;
}

.module-eyebrow {
  margin: 0 0 var(--space-1);
  color: var(--color-primary);
  font-size: 0.76rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.info-card {
  padding: var(--space-4);
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-lg);
  background: var(--color-brand-primary-tint);
}

.info-card p {
  margin: 0;
  color: var(--color-text-muted);
  line-height: 1.15;
}

.module-content {
  padding: var(--space-5);
  border: 1px solid var(--color-border-default);
  border-radius: var(--radius-lg);
  background: var(--color-bg-panel);
}
</style>
