// Nombre de archivo: useSla.ts
// Ubicación de archivo: web/frontend/src/composables/useSla.ts
// Descripción: Composable del flujo SLA con tipado estricto, estado reactivo y llamada segura al endpoint web

import { ref } from 'vue';
import { request } from '../api/client';

export interface SlaPayload {
  mes: number;
  anio: number;
  periodo_mes: number;
  periodo_anio: number;
  pdf_enabled: boolean;
  use_db: boolean;
  files: File[];
}

interface SlaResponse {
  ok?: boolean;
  message?: string;
  report_paths?: Record<string, string>;
  error?: string;
  detail?: string;
}

type FlashTone = 'muted' | 'info' | 'success' | 'error';

export function useSla() {
  const selectedFiles = ref<File[]>([]);
  const reportPaths = ref<Record<string, string>>({});
  const loading = ref(false);
  const flashText = ref('Subí ambos archivos Excel o activá "Usar base" y completá el período.');
  const flashClass = ref<FlashTone>('muted');

  function setFlash(text: string, tone: FlashTone): void {
    flashText.value = text;
    flashClass.value = tone;
  }

  function resetResults(): void {
    reportPaths.value = {};
  }

  function setSelectedFiles(files: File[]): void {
    selectedFiles.value = files;
    resetResults();
  }

  async function generate(payload: SlaPayload): Promise<void> {
    resetResults();

    if (!payload.use_db && payload.files.length !== 2) {
      setFlash('Debés adjuntar dos archivos: Servicios Fuera de SLA y Reclamos SLA.', 'error');
      return;
    }

    if (!payload.mes || !payload.anio) {
      setFlash('Indicá mes y año válidos.', 'error');
      return;
    }

    loading.value = true;
    setFlash('Procesando informe...', 'info');

    const formData = new FormData();
    formData.append('mes', String(payload.mes));
    formData.append('anio', String(payload.anio));
    formData.append('periodo_mes', String(payload.periodo_mes));
    formData.append('periodo_anio', String(payload.periodo_anio));
    formData.append('pdf_enabled', payload.pdf_enabled ? 'true' : 'false');
    formData.append('use_db', payload.use_db ? 'true' : 'false');
    if (!payload.use_db) {
      payload.files.forEach((file) => formData.append('files', file, file.name));
    }

    try {
      const response = await request('/api/reports/sla', {
        method: 'POST',
        formData,
        csrf: true,
        throwOnError: false,
      });
      const data = await response.json().catch(() => ({})) as SlaResponse;
      if (!response.ok || data.ok === false) {
        throw new Error(data.error ?? data.detail ?? data.message ?? `Error ${response.status}`);
      }
      setFlash(data.message ?? 'Informe SLA generado correctamente.', 'success');
      reportPaths.value = data.report_paths ?? {};
    } catch (error) {
      setFlash(`Error: ${error instanceof Error ? error.message : String(error)}`, 'error');
    } finally {
      loading.value = false;
    }
  }

  return {
    selectedFiles,
    reportPaths,
    loading,
    flashText,
    flashClass,
    setSelectedFiles,
    setFlash,
    generate,
  };
}