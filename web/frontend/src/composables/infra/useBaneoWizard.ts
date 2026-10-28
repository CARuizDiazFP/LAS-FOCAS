// Nombre de archivo: useBaneoWizard.ts
// Ubicación de archivo: web/frontend/src/composables/infra/useBaneoWizard.ts
// Descripción: Estado y acciones del wizard de 3 pasos del Protocolo de Protección (alta de baneo)

import { ref, computed } from 'vue';
import { ApiError } from '../../api/client';
import {
  crearBaneo,
  descargarTrackingRuta,
  rutasDeServicio,
  type BanRutaOption,
} from '../../api/infra';
import type { Notificar } from './tipos';

interface BanFormData {
  ticket_asociado: string;
  servicio_afectado_id: string;
  servicio_protegido_id: string;
  motivo: string;
  usuario_ejecutor: string;
}

/**
 * @param notificar toast de InfraTab.
 * @param alCrear se invoca tras crear el baneo con éxito; `await` sólo cubre callbacks que devuelvan promesa: `emit` no devuelve la del listener del padre.
 */
export function useBaneoWizard(notificar: Notificar, alCrear: () => void | Promise<void>) {
  const banModalEl = ref<HTMLDialogElement | null>(null);
  const banLoading = ref(false);
  const currentBanStep = ref<1 | 2 | 3>(1);
  const banProtMode = ref<'same' | 'other'>('same');
  const banSearchServicioInput = ref('');
  const banRutas = ref<BanRutaOption[]>([]);
  const banLoadingRutas = ref(false);
  const banRutasError = ref('');
  const banSelectedRutaId = ref<number | null>(null);
  const banConfirmChecked = ref(false);

  const banForm = ref<BanFormData>({
    ticket_asociado: '',
    servicio_afectado_id: '',
    servicio_protegido_id: '',
    motivo: '',
    usuario_ejecutor: '',
  });

  function resetBanModalState() {
    banForm.value = { ticket_asociado: '', servicio_afectado_id: '', servicio_protegido_id: '', motivo: '', usuario_ejecutor: '' };
    currentBanStep.value = 1;
    banProtMode.value = 'same';
    banSearchServicioInput.value = '';
    banRutas.value = [];
    banLoadingRutas.value = false;
    banRutasError.value = '';
    banSelectedRutaId.value = null;
    banConfirmChecked.value = false;
  }

  const banEstimatedCamaras = computed<number>(() => {
    if (banSelectedRutaId.value === null) {
      return banRutas.value.filter(r => r.activa).reduce((s, r) => s + r.empalmes_count, 0);
    }
    return banRutas.value.find(r => r.id === banSelectedRutaId.value)?.empalmes_count ?? 0;
  });

  function abrir() {
    resetBanModalState();
    banModalEl.value?.showModal();
  }

  // Siempre se llama con paréntesis: con `@click="cerrar"` Vue pasaría el MouseEvent como
  // `force` (truthy) y el modal se cerraría durante "Activando...", saltándose la guarda.
  function cerrar(force = false) {
    if (banLoading.value && !force) return;
    banModalEl.value?.close();
    resetBanModalState();
  }

  // Cierra el dialog sin resetear el wizard (lo usa "Actualizar Tracking"; abrir() resetea igual).
  function ocultar() {
    banModalEl.value?.close();
  }

  async function loadRutasForBan(servicioId: string) {
    if (!servicioId) return;
    banLoadingRutas.value = true;
    banRutasError.value = '';
    banRutas.value = [];
    banSelectedRutaId.value = null;
    banForm.value.servicio_protegido_id = servicioId;
    try {
      const data = await rutasDeServicio(servicioId);
      banRutas.value = data.rutas ?? [];
      if (banRutas.value.length === 0) banRutasError.value = `El servicio ${servicioId} no tiene rutas registradas.`;
    } catch (e: unknown) {
      banRutasError.value = e instanceof Error ? e.message : String(e);
      banForm.value.servicio_protegido_id = '';
    } finally {
      banLoadingRutas.value = false;
    }
  }

  function banSwitchMode(mode: 'same' | 'other') {
    if (banProtMode.value === mode) return;
    banProtMode.value = mode;
    banRutas.value = [];
    banRutasError.value = '';
    banSelectedRutaId.value = null;
    banSearchServicioInput.value = '';
    banForm.value.servicio_protegido_id = '';
    if (mode === 'same') {
      void loadRutasForBan(banForm.value.servicio_afectado_id.trim());
    }
  }

  async function banGoNext() {
    if (currentBanStep.value === 1) {
      if (!banForm.value.servicio_afectado_id.trim()) {
        notificar('warning', 'Campo requerido', 'Ingresá el ID del servicio afectado');
        return;
      }
      currentBanStep.value = 2;
      if (banProtMode.value === 'same') {
        await loadRutasForBan(banForm.value.servicio_afectado_id.trim());
      }
    } else if (currentBanStep.value === 2) {
      if (!banForm.value.servicio_protegido_id.trim()) {
        notificar('warning', 'Servicio requerido', banProtMode.value === 'other' ? 'Buscá un servicio para proteger' : 'No se pudo cargar el servicio');
        return;
      }
      currentBanStep.value = 3;
    }
  }

  function banGoPrev() {
    if (currentBanStep.value > 1) currentBanStep.value = (currentBanStep.value - 1) as 1 | 2 | 3;
  }

  // Descarga tracking de una ruta directamente (sin abrir el modal de tracking)
  async function downloadTrackingByRutaId(rutaId: number) {
    try {
      const filename = await descargarTrackingRuta(rutaId);
      notificar('success', 'Descarga completa', filename);
    } catch (e: unknown) {
      if (e instanceof ApiError && e.status === 404) { notificar('warning', 'Sin archivo', 'El TXT original no está disponible'); return; }
      notificar('error', 'Error de descarga', e instanceof Error ? e.message : String(e));
    }
  }

  async function submitBan() {
    if (!banForm.value.servicio_afectado_id.trim() || !banForm.value.servicio_protegido_id.trim()) {
      notificar('warning', 'Campos requeridos', 'Faltan datos del servicio');
      return;
    }
    banLoading.value = true;
    try {
      const payload = {
        ticket_asociado: banForm.value.ticket_asociado.trim() || null,
        servicio_afectado_id: banForm.value.servicio_afectado_id.trim(),
        servicio_protegido_id: banForm.value.servicio_protegido_id.trim(),
        ruta_protegida_id: banSelectedRutaId.value,
        motivo: banForm.value.motivo.trim() || null,
        usuario_ejecutor: banForm.value.usuario_ejecutor.trim() || null,
      };
      const data = await crearBaneo(payload);
      cerrar(true);
      const baneadas = data.camaras_baneadas ?? 0;
      notificar('success', 'Protocolo activado', `${baneadas} cámara(s) baneadas`);
      await alCrear();
    } catch (e: unknown) {
      notificar('error', 'Error al activar protocolo', e instanceof Error ? e.message : String(e));
    } finally {
      banLoading.value = false;
    }
  }

  return {
    banModalEl,
    banLoading,
    currentBanStep,
    banProtMode,
    banSearchServicioInput,
    banRutas,
    banLoadingRutas,
    banRutasError,
    banSelectedRutaId,
    banConfirmChecked,
    banForm,
    banEstimatedCamaras,
    abrir,
    cerrar,
    ocultar,
    loadRutasForBan,
    banSwitchMode,
    banGoNext,
    banGoPrev,
    downloadTrackingByRutaId,
    submitBan,
  };
}
