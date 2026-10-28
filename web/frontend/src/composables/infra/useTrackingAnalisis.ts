// Nombre de archivo: useTrackingAnalisis.ts
// Ubicación de archivo: web/frontend/src/composables/infra/useTrackingAnalisis.ts
// Descripción: Subida de tracking de InfraTab (flujo Portero 2 fases): elección del .txt (input oculto y drag&drop), análisis y resolución

import { ref } from 'vue';
import {
  analizarTracking,
  resolverTracking,
  type AnalyzeResult,
  type ResolverTrackingBody,
} from '../../api/infra';
import type { Notificar } from './tipos';

/**
 * Elección del archivo: input oculto + zona de drag&drop (viven en InfraTab).
 * @param alLeer recibe el contenido y el nombre del .txt leído; dispara el análisis.
 */
export function useTrackingAnalisis(notificar: Notificar, alLeer: (contenido: string, nombre: string) => void) {
  const trackingFileInputEl = ref<HTMLInputElement | null>(null);
  // --- Drag & Drop para la zona de upload de tracking ---
  const isDragOver = ref(false);

  function elegirArchivo() {
    trackingFileInputEl.value?.click();
  }

  function onDragOver() {
    isDragOver.value = true;
  }

  function onDragEnter() {
    isDragOver.value = true;
  }

  function onDragLeave(e: DragEvent) {
    // Solo desactivar si el mouse salió del wrapper completo
    const target = e.currentTarget as HTMLElement;
    if (!target.contains(e.relatedTarget as Node)) {
      isDragOver.value = false;
    }
  }

  function onDrop(e: DragEvent) {
    isDragOver.value = false;
    const file = e.dataTransfer?.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.txt')) {
      notificar('warning', 'Archivo inválido', 'Solo se aceptan archivos .txt');
      return;
    }
    const reader = new FileReader();
    reader.onload = (ev) => {
      alLeer((ev.target?.result as string) ?? '', file.name);
    };
    reader.readAsText(file, 'utf-8');
  }

  function onArchivoElegido(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.txt')) {
      notificar('warning', 'Archivo inválido', 'Solo se aceptan archivos .txt');
      return;
    }
    const reader = new FileReader();
    reader.onload = (e) => {
      alLeer((e.target?.result as string) ?? '', file.name);
    };
    reader.readAsText(file, 'utf-8');
  }

  return {
    trackingFileInputEl,
    isDragOver,
    elegirArchivo,
    onDragOver,
    onDragEnter,
    onDragLeave,
    onDrop,
    onArchivoElegido,
  };
}

/**
 * Análisis y resolución del tracking leído (modal de resolución).
 * @param alResolver se invoca (y se espera) tras resolver el tracking con éxito.
 */
export function useResolucionTracking(notificar: Notificar, alResolver: () => void | Promise<void>) {
  const trackingResolveModalEl = ref<HTMLDialogElement | null>(null);
  const uploadAnalyzing = ref(false);
  const uploadResolving = ref(false);
  const analyzeResult = ref<AnalyzeResult | null>(null);
  const fileContent = ref('');
  const fileName = ref('');
  const resolveTargetRutaId = ref<number | null>(null);
  const resolveNewRutaNombre = ref('');

  // Recibe el .txt ya leído, abre el modal y lo analiza.
  function abrir(contenido: string, nombre: string) {
    fileContent.value = contenido;
    fileName.value = nombre;
    void analyzeTracking();
  }

  async function analyzeTracking() {
    uploadAnalyzing.value = true;
    analyzeResult.value = null;
    resolveTargetRutaId.value = null;
    resolveNewRutaNombre.value = '';
    trackingResolveModalEl.value?.showModal();
    try {
      const blob = new Blob([fileContent.value], { type: 'text/plain' });
      const formData = new FormData();
      formData.append('file', blob, fileName.value);
      analyzeResult.value = await analizarTracking(formData);
      if (analyzeResult.value.rutas_existentes?.length) {
        resolveTargetRutaId.value = analyzeResult.value.rutas_existentes[0].id;
      }
    } catch (e: unknown) {
      analyzeResult.value = {
        status: 'ERROR', message: 'Error analizando el archivo',
        parsed_empalmes_count: 0, rutas_existentes: [],
        error: e instanceof Error ? e.message : String(e),
      };
    } finally {
      uploadAnalyzing.value = false;
    }
  }

  async function resolveTracking(action: string, extras: Partial<ResolverTrackingBody> = {}) {
    uploadResolving.value = true;
    try {
      const body: ResolverTrackingBody = {
        action,
        content: fileContent.value,
        filename: fileName.value,
        ...extras,
      };
      const data = await resolverTracking(body);
      if (!data.success) {
        throw new Error(data.error ?? 'Error al resolver el tracking');
      }
      cerrar();
      notificar('success', 'Tracking procesado', data.message ?? '');
      if (data.ubicaciones_sin_match && data.ubicaciones_sin_match > 0) {
        notificar(
          'warning',
          'Ubicaciones sin match',
          `${data.ubicaciones_sin_match} ubicación(es) sin cámara/botella asociada — revisar en Ingresos sin match`,
        );
      }
      await alResolver();
    } catch (e: unknown) {
      notificar('error', 'Error al procesar tracking', e instanceof Error ? e.message : String(e));
    } finally {
      uploadResolving.value = false;
    }
  }

  function cerrar() {
    trackingResolveModalEl.value?.close();
    uploadAnalyzing.value = false;
    analyzeResult.value = null;
    fileContent.value = '';
    fileName.value = '';
    resolveTargetRutaId.value = null;
    resolveNewRutaNombre.value = '';
  }

  return {
    trackingResolveModalEl,
    uploadAnalyzing,
    uploadResolving,
    analyzeResult,
    fileName,
    resolveTargetRutaId,
    resolveNewRutaNombre,
    abrir,
    resolveTracking,
    cerrar,
  };
}
