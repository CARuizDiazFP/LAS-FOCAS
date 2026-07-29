<!--
  Nombre de archivo: CienaTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/CienaTab.vue
  Descripción: Tab Alarmas Ciena — convierte CSV SiteManager/MCP a Excel — migrado desde panel.js
-->
<template>
  <article class="module-screen card">
    <header class="module-header">
      <div class="module-heading">
        <p class="module-eyebrow">DWDM Ciena</p>
        <h1>Alarmas Ciena</h1>
      </div>
      <span class="badge">Nuevo</span>
    </header>

    <section class="info-card" aria-label="Contexto del submódulo Alarmas Ciena">
      <p>
        Utilice esta pantalla para cargar un CSV exportado desde SiteManager o MCP, normalizar su contenido y
        convertirlo a un archivo Excel listo para revisión operativa o distribución interna.
      </p>
    </section>

    <main class="module-content">
      <div class="stack">
        <div
          class="dropzone"
          :class="{ drag: isDrag }"
          @click="fileEl?.click()"
          @dragover.prevent="isDrag = true"
          @dragleave="isDrag = false"
          @drop.prevent="handleDrop"
        >
          <input ref="fileEl" type="file" accept=".csv" hidden @change="onFileChange" />
          <span>{{ selectedFile ? `Seleccionado: ${selectedFile.name}` : 'Arrastrá el .csv acá o hacé click' }}</span>
        </div>
        <div class="card-actions">
          <button class="btn primary" :disabled="loading" @click="process">Procesar</button>
        </div>
      </div>
      <div :class="['result-box', resultClass]" role="status" aria-live="polite">{{ resultText }}</div>
    </main>
  </article>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useCiena } from '../../composables/useCiena';

const isDrag = ref(false);
const fileEl = ref<HTMLInputElement | null>(null);
const {
  selectedFile,
  loading,
  resultText,
  resultClass,
  setSelectedFile,
  process,
} = useCiena();

function onFileChange(e: Event) {
  setSelectedFile((e.target as HTMLInputElement).files?.[0] ?? null);
}

function handleDrop(e: DragEvent) {
  isDrag.value = false;
  setSelectedFile(e.dataTransfer?.files?.[0] ?? null);
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
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
</style>
