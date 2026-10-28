// Nombre de archivo: useCiena.ts
// Ubicación de archivo: web/frontend/src/composables/useCiena.ts
// Descripción: Composable del flujo Alarmas Ciena con estado reactivo, descarga segura y parsing de metadatos

import { ref } from 'vue';
import { procesarAlarmasCiena } from '../api/herramientas';

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

    try {
      const { blob, formato, filas, columnas } = await procesarAlarmasCiena(selectedFile.value);

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