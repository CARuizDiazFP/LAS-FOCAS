// Nombre de archivo: useCiena.ts
// Ubicación de archivo: web/frontend/src/composables/useCiena.ts
// Descripción: Composable del flujo Alarmas Ciena con estado reactivo, descarga segura y parsing de metadatos

import { ref } from 'vue';
import { request } from '../api/client';

type ResultTone = 'muted' | 'info' | 'success' | 'error';

function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export function useCiena() {
  const selectedFile = ref<File | null>(null);
  const loading = ref(false);
  const resultText = ref('Esperando archivo.');
  const resultClass = ref<ResultTone>('muted');

  function setSelectedFile(file: File | null): void {
    selectedFile.value = file;
    resultText.value = 'Esperando archivo.';
    resultClass.value = 'muted';
  }

  async function process(): Promise<void> {
    if (!selectedFile.value) {
      resultText.value = 'Seleccioná un archivo CSV';
      resultClass.value = 'error';
      return;
    }

    loading.value = true;
    resultText.value = 'Procesando...';
    resultClass.value = 'info';

    const formData = new FormData();
    formData.append('file', selectedFile.value);

    try {
      const response = await request('/api/tools/alarmas-ciena', {
        method: 'POST',
        formData,
        csrf: true,
      });
      const formato = response.headers.get('X-Formato-Detectado') ?? 'desconocido';
      const filas = response.headers.get('X-Filas-Procesadas') ?? '?';
      const columnas = response.headers.get('X-Columnas') ?? '?';
      const blob = await response.blob();

      triggerDownload(blob, selectedFile.value.name.replace(/\.csv$/i, '') + '_procesado.xlsx');

      resultText.value = `✔ Convertido (formato: ${formato}, ${filas} filas, ${columnas} columnas). La descarga comenzó.`;
      resultClass.value = 'success';
    } catch (error) {
      resultText.value = `Error: ${error instanceof Error ? error.message : String(error)}`;
      resultClass.value = 'error';
    } finally {
      loading.value = false;
    }
  }

  return {
    selectedFile,
    loading,
    resultText,
    resultClass,
    setSelectedFile,
    process,
  };
}