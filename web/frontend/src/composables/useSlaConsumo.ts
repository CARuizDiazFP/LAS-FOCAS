// Nombre de archivo: useSlaConsumo.ts
// Ubicación de archivo: web/frontend/src/composables/useSlaConsumo.ts
// Descripción: Estado y llamada al informe de SLA consumido (persiste el histórico de reclamos)

import { ref } from 'vue';
import { request } from '../api/client';

export interface SlaConsumoTotales {
  reclamos?: number;
  eventos?: number;
  reclamos_aislados?: number;
  servicios?: number;
  servicios_excedidos?: number;
  horas?: number;
  horas_sla?: number;
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
  totales?: SlaConsumoTotales;
  report_paths?: Record<string, string>;
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
      mensaje.value = data.ya_ingestado
        ? `Corte ${data.fecha_corte}: estos archivos ya estaban ingestados; informe regenerado.`
        : `Corte ${data.fecha_corte}: ${data.reclamos_insertados ?? 0} reclamos nuevos, ${data.reclamos_actualizados ?? 0} actualizados.`;
      tono.value = 'success';
    } catch (err) {
      mensaje.value = err instanceof Error ? err.message : 'Error de red';
      tono.value = 'error';
    } finally {
      loading.value = false;
    }
  }

  return { archivos, resultado, loading, mensaje, tono, setArchivos, generar };
}
