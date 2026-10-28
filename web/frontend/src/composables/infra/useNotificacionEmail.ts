// Nombre de archivo: useNotificacionEmail.ts
// Ubicación de archivo: web/frontend/src/composables/infra/useNotificacionEmail.ts
// Descripción: Aviso por email de un baneo activo: plantilla local, envío, descarga del .eml y destinatarios guardados

import { ref } from 'vue';
import { descargarEmlBaneo, notificarBaneoEmail, type IncidenteActivo } from '../../api/infra';
import type { Notificar } from './tipos';

interface AvisoForm {
  to: string;
  cc: string;
  subject: string;
  body: string;
  include_xls: boolean;
  include_txt: boolean;
}

// --- Plantilla por defecto ---
function buildAvisoBody(inc: IncidenteActivo, fechaHora: string): string {
  const lineas = [
    'Estimados,',
    '',
    'Se les informa que se ha activado el Protocolo de Protección en la red de fibra óptica debido a una afectación de servicio.',
    '',
    'DATOS DEL INCIDENTE:',
    `• Ticket: ${inc.ticket_asociado ?? 'Sin ticket'}`,
    `• Servicio Afectado: ${inc.servicio_afectado_id}`,
    `• Servicio Protegido: ${inc.servicio_protegido_id}`,
    `• Cámaras Restringidas: ${inc.camaras_count} cámara${inc.camaras_count !== 1 ? 's' : ''}`,
    `• Fecha/Hora: ${fechaHora}`,
    `• Motivo: ${inc.motivo ?? 'No especificado'}`,
    '',
    'Se adjunta el listado detallado de cámaras restringidas (Excel) y el archivo de tracking original.',
    '',
    'Por favor, tomar las precauciones necesarias y abstenerse de realizar trabajos en las cámaras listadas hasta nuevo aviso.',
    '',
    'Saludos cordiales,',
    'Operaciones de Red',
    'Metrotel S.A.',
    '',
    'Generado por LAS-FOCAS - Metrotel',
  ];
  return lineas.join('\n');
}

export function useNotificacionEmail(notificar: Notificar) {
  const avisoModalEl = ref<HTMLDialogElement | null>(null);
  const avisoIncidente = ref<IncidenteActivo | null>(null);
  const avisoSending = ref(false);
  const avisoForm = ref<AvisoForm>({
    to: '', cc: '', subject: '', body: '', include_xls: true, include_txt: true,
  });

  function saveAvisoDestinatarios() {
    try {
      localStorage.setItem('focas_baneo_to', avisoForm.value.to.trim());
      localStorage.setItem('focas_baneo_cc', avisoForm.value.cc.trim());
    } catch { /* localStorage no disponible */ }
  }

  function abrir(inc: IncidenteActivo) {
    avisoIncidente.value = inc;
    avisoForm.value.include_xls = true;
    avisoForm.value.include_txt = true;

    // Restaurar destinatarios desde localStorage
    try {
      avisoForm.value.to = localStorage.getItem('focas_baneo_to') ?? '';
      avisoForm.value.cc = localStorage.getItem('focas_baneo_cc') ?? '';
    } catch {
      avisoForm.value.to = '';
      avisoForm.value.cc = '';
    }

    // Plantilla por defecto con datos del incidente
    const ahora = new Date().toLocaleString('es-AR', {
      day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    });
    avisoForm.value.subject = '[AVISO] BANEO de Camaras';
    avisoForm.value.body = buildAvisoBody(inc, ahora);

    avisoModalEl.value?.showModal();
  }

  // Siempre se llama con paréntesis (el evento no debe llegar como `force`). Durante el envío no
  // cierra salvo `force`; sendAviso() fuerza porque avisoSending recién baja en su `finally`.
  function cerrar(force = false) {
    if (avisoSending.value && !force) return;
    avisoModalEl.value?.close();
    avisoIncidente.value = null;
  }

  async function sendAviso() {
    if (!avisoIncidente.value) return;
    const toList = avisoForm.value.to.split(',').map(s => s.trim()).filter(Boolean);
    const ccList = avisoForm.value.cc.split(',').map(s => s.trim()).filter(Boolean);
    if (toList.length === 0) {
      notificar('warning', 'Destinatarios requeridos', 'Ingresá al menos un destinatario');
      return;
    }
    saveAvisoDestinatarios();
    avisoSending.value = true;
    try {
      const data = await notificarBaneoEmail({
        to: toList,
        cc: ccList.length ? ccList : undefined,
        subject: avisoForm.value.subject.trim(),
        body: avisoForm.value.body.trim(),
        incidente_ids: [avisoIncidente.value.id],
        include_xls: avisoForm.value.include_xls,
        include_txt: avisoForm.value.include_txt,
      });
      if (!data.success) {
        throw new Error(data.error ?? data.detail ?? 'Error al enviar el aviso');
      }
      cerrar(true);
      notificar('success', 'Aviso enviado', `Notificación enviada a ${toList.length} destinatario${toList.length !== 1 ? 's' : ''}`);
    } catch (e: unknown) {
      notificar('error', 'Error al enviar aviso', e instanceof Error ? e.message : String(e));
    } finally {
      avisoSending.value = false;
    }
  }

  async function downloadEml() {
    if (!avisoIncidente.value) return;
    saveAvisoDestinatarios();
    const toList = avisoForm.value.to.split(',').map(s => s.trim()).filter(Boolean);
    try {
      const filename = await descargarEmlBaneo({
        incident_id: avisoIncidente.value.id,
        recipients: toList.join(', '),
        subject: avisoForm.value.subject.trim(),
        html_body: avisoForm.value.body.trim(),
      });
      notificar('success', 'EML descargado', filename);
    } catch (e: unknown) {
      notificar('error', 'Error al generar EML', e instanceof Error ? e.message : String(e));
    }
  }

  return {
    avisoModalEl,
    avisoIncidente,
    avisoSending,
    avisoForm,
    abrir,
    cerrar,
    sendAviso,
    downloadEml,
  };
}
