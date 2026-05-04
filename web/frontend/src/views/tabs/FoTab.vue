<!--
  Nombre de archivo: FoTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/FoTab.vue
  Descripción: Tab Comparador FO (WIP) — migrado desde panel.js
-->
<template>
  <article class="card">
    <header class="card-header">
      <h1>Comparador FO</h1>
      <span class="badge">WIP</span>
    </header>
    <div class="stack">
      <div
        class="dropzone"
        :class="{ drag: isDrag }"
        @click="fileEl?.click()"
        @dragover.prevent="isDrag = true"
        @dragleave="isDrag = false"
        @drop.prevent="handleDrop"
      >
        <input ref="fileEl" type="file" accept=".xlsx,.csv" hidden @change="onFileChange" />
        <span>{{ selectedFile ? `Seleccionado: ${selectedFile.name}` : 'Arrastrá el archivo o hacé click' }}</span>
      </div>
      <div class="card-actions">
        <button class="btn" @click="run">Comparar</button>
      </div>
    </div>
    <div :class="['result-box', resultClass]">{{ resultText }}</div>
  </article>
</template>

<script setup lang="ts">
import { ref } from 'vue';

const isDrag = ref(false);
const fileEl = ref<HTMLInputElement | null>(null);
const resultText = ref('No implementado aún.');
const resultClass = ref('muted');
let selectedFile: File | null = null;

function onFileChange(e: Event) {
  selectedFile = (e.target as HTMLInputElement).files?.[0] ?? null;
}

function handleDrop(e: DragEvent) {
  isDrag.value = false;
  selectedFile = e.dataTransfer?.files?.[0] ?? null;
}

function run() {
  resultText.value = 'No implementado aún';
  resultClass.value = 'info';
}
</script>
