<!--
  Nombre de archivo: CienaTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/CienaTab.vue
  Descripción: Tab Alarmas Ciena — convierte CSV SiteManager/MCP a Excel — migrado desde panel.js
-->
<template>
  <article class="card">
    <header class="card-header">
      <h1>Alarmas Ciena</h1>
      <span class="badge">Nuevo</span>
    </header>
    <p class="muted">Seleccioná un CSV exportado desde SiteManager o MCP para convertirlo a Excel.</p>
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
    <div :class="['result-box', resultClass]">{{ resultText }}</div>
  </article>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useSession } from '../../composables/useSession';

const { csrf } = useSession();
const isDrag = ref(false);
const loading = ref(false);
const resultText = ref('Esperando archivo.');
const resultClass = ref('muted');
const fileEl = ref<HTMLInputElement | null>(null);
let selectedFile: File | null = null;

function onFileChange(e: Event) {
  selectedFile = (e.target as HTMLInputElement).files?.[0] ?? null;
  resultText.value = 'Esperando archivo.';
  resultClass.value = 'muted';
}

function handleDrop(e: DragEvent) {
  isDrag.value = false;
  selectedFile = e.dataTransfer?.files?.[0] ?? null;
}

async function process() {
  if (!selectedFile) {
    resultText.value = 'Seleccioná un archivo CSV';
    resultClass.value = 'error';
    return;
  }
  resultText.value = 'Procesando...';
  resultClass.value = 'info';
  loading.value = true;
  const fd = new FormData();
  fd.append('file', selectedFile);
  fd.append('csrf_token', csrf());
  try {
    const res = await fetch('/api/tools/alarmas-ciena', { method: 'POST', body: fd, credentials: 'include' });
    if (!res.ok) {
      let errMsg = 'Error al procesar el archivo';
      try {
        const errData = await res.json();
        if (errData.error) errMsg = errData.error;
        else if (errData.detail) errMsg = errData.detail;
      } catch { /* ignorar */ }
      throw new Error(errMsg);
    }
    const formato = res.headers.get('X-Formato-Detectado') ?? 'desconocido';
    const filas = res.headers.get('X-Filas-Procesadas') ?? '?';
    const columnas = res.headers.get('X-Columnas') ?? '?';
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = selectedFile.name.replace(/\.csv$/i, '') + '_procesado.xlsx';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    resultText.value = `✔ Convertido (formato: ${formato}, ${filas} filas, ${columnas} columnas). La descarga comenzó.`;
    resultClass.value = 'success';
  } catch (e: unknown) {
    resultText.value = `Error: ${e instanceof Error ? e.message : String(e)}`;
    resultClass.value = 'error';
  } finally {
    loading.value = false;
  }
}
</script>
