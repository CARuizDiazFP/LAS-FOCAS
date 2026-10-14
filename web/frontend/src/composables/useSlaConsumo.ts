// Nombre de archivo: useSlaConsumo.ts
// Ubicación de archivo: web/frontend/src/composables/useSlaConsumo.ts
// Descripción: Estado y llamada al informe de SLA consumido (persiste el histórico de reclamos)

import { ref } from 'vue';
import { request } from '../api/client';

export interface SlaConsumoTotales {
  servicios_universo?: number;
  servicios_con_reclamos?: number;
  servicios_dentro?: number;
  servicios_agotados?: number;
  servicios_excedidos?: number;
  servicios_sin_consumo?: number;
  servicios_no_evaluables?: number;
  reclamos?: number;
  reclamos_vinculados?: number;
  reclamos_no_vinculados?: number;
  eventos?: number;
  reclamos_sin_evento?: number;
  horas_netas?: number;
  horas_computables?: number;
  horas_excluidas?: number;
  horas_no_vinculadas?: number;
  horas_fo_general?: number;
  horas_fo_cod3?: number;
  horas_carrier?: number;
  horas_otros?: number;
  inconsistencias?: number;
}

export interface SlaConsumoReportPaths {
  xlsx?: string;
  docx_ejecutivo?: string;
  docx_exhaustivo?: string;
  pdf_ejecutivo?: string;
  pdf_exhaustivo?: string;
}

export interface SlaConsumoResultado {
  ok?: boolean;
  message?: string;
  error?: string;
  detail?: string;
  fecha_corte?: string;
  ya_ingestado?: boolean;
  reclamos_insertados?: number;
  reclamos_actualizados?: number;
  reclamos_sin_cambios?: number;
  pdf_omitido?: string;
  totales?: SlaConsumoTotales;
  report_paths?: SlaConsumoReportPaths;
}

type Tono = 'muted' | 'info' | 'success' | 'error';

export function useSlaConsumo() {
  const archivos = ref<File[]>([]);
  const resultado = ref<SlaConsumoResultado | null>(null);
  const loading = ref(false);
  const mensaje = ref('Subí los Excel de Servicios y Reclamos. Los reclamos quedan guardados en el histórico.');
  const tono = ref<Tono>('muted');

  function setArchivos(files: File[]): void {
    archivos.value = files;
    resultado.value = null;
  }

  async function generar(pdf: boolean): Promise<void> {
    resultado.value = null;
    if (archivos.value.length !== 2) {
      mensaje.value = 'Adjuntá exactamente dos archivos: Servicios y Reclamos.';
      tono.value = 'error';
      return;
    }
    const formData = new FormData();
    archivos.value.forEach((f) => formData.append('files', f, f.name));
    formData.append('pdf_enabled', pdf ? 'true' : 'false');
    loading.value = true;
    mensaje.value = 'Procesando…';
    tono.value = 'info';
    try {
      const response = await request('/api/reports/sla-consumo', {
        method: 'POST',
        formData,
        csrf: true,
        throwOnError: false,
      });
      const data = (await response.json().catch(() => ({}))) as SlaConsumoResultado;
      if (!response.ok || data.ok === false) {
        throw new Error(data.error ?? data.detail ?? data.message ?? `Error ${response.status}`);
      }
      resultado.value = data;
      const sinCambios = data.reclamos_sin_cambios
        ? `, ${data.reclamos_sin_cambios} sin cambios (ya tenían datos de un corte más nuevo)`
        : '';
      const base = data.ya_ingestado
        ? `Corte ${data.fecha_corte}: estos archivos ya estaban ingestados; informe regenerado.`
        : `Corte ${data.fecha_corte}: ${data.reclamos_insertados ?? 0} reclamos nuevos, ${data.reclamos_actualizados ?? 0} actualizados${sinCambios}.`;
      mensaje.value = data.pdf_omitido ? `${base} PDF no generado: ${data.pdf_omitido}.` : base;
      tono.value = data.pdf_omitido ? 'info' : 'success';
    } catch (err) {
      mensaje.value = err instanceof Error ? err.message : 'Error de red';
      tono.value = 'error';
    } finally {
      loading.value = false;
    }
  }

  return { archivos, resultado, loading, mensaje, tono, setArchivos, generar };
}
