// Nombre de archivo: useBaneosActivos.ts
// Ubicación de archivo: web/frontend/src/composables/infra/useBaneosActivos.ts
// Descripción: Lista de baneos activos y levantamiento de baneo para el modal de InfraTab

import { ref } from 'vue';
import { baneosActivos, levantarBaneo, type IncidenteActivo } from '../../api/infra';
import type { Notificar } from './tipos';

function formatDuracion(horas: number | null): string {
  if (horas === null || horas === undefined) return '';
  if (horas < 1) return `${Math.round(horas * 60)} min`;
  return `${horas.toFixed(1)} h`;
}

function formatFecha(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/**
 * @param notificar toast de InfraTab.
 * @param alLevantar se invoca (y se espera) tras levantar un baneo y recargar la lista.
 */
export function useBaneosActivos(notificar: Notificar, alLevantar: () => void | Promise<void>) {
  const activeBansModalEl = ref<HTMLDialogElement | null>(null);
  const activeBans = ref<IncidenteActivo[]>([]);
  const activeBansLoading = ref(false);
  const activeBansError = ref('');
  const liftLoadingId = ref<number | null>(null);

  async function loadActiveBans() {
    activeBansLoading.value = true;
    activeBansError.value = '';
    try {
      const data = await baneosActivos();
      activeBans.value = data.incidentes ?? [];
    } catch (e: unknown) {
      activeBansError.value = e instanceof Error ? e.message : String(e);
    } finally {
      activeBansLoading.value = false;
    }
  }

  function abrir() {
    activeBansError.value = '';
    activeBansModalEl.value?.showModal();
    void loadActiveBans();
  }

  function cerrar() {
    activeBansModalEl.value?.close();
  }

  async function confirmLiftBan(inc: IncidenteActivo) {
    const ticket = inc.ticket_asociado ? `#${inc.ticket_asociado}` : `ID ${inc.id}`;
    if (!window.confirm(`¿Levantar el baneo ${ticket}?\n\nSe restaurarán las cámaras del servicio ${inc.servicio_protegido_id} y se notificará en Slack.`)) return;
    liftLoadingId.value = inc.id;
    try {
      await levantarBaneo({ incidente_id: inc.id });
      notificar('success', 'Baneo levantado', `Servicio ${inc.servicio_protegido_id} restaurado`);
      await loadActiveBans();
      await alLevantar();
    } catch (e: unknown) {
      notificar('error', 'Error al levantar baneo', e instanceof Error ? e.message : String(e));
    } finally {
      liftLoadingId.value = null;
    }
  }

  return {
    activeBansModalEl,
    activeBans,
    activeBansLoading,
    activeBansError,
    liftLoadingId,
    loadActiveBans,
    abrir,
    cerrar,
    confirmLiftBan,
    formatDuracion,
    formatFecha,
  };
}
