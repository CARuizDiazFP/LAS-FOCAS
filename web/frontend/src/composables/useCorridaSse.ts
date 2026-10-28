// Nombre de archivo: useCorridaSse.ts
// Ubicación de archivo: web/frontend/src/composables/useCorridaSse.ts
// Descripción: Suscripción al SSE de corridas de Cromo (/api/admin/ingesta/cromo/corridas/{id}/stream) con reanudación por ?desde= y backoff; distingue el evento de negocio `error` de la caída de la conexión

import { onBeforeUnmount } from 'vue';

const BACKOFF_INICIAL_MS = 2000;
const BACKOFF_MAXIMO_MS = 30000;

/** Mismo SSE que las corridas de ingesta. `desde` es el último id de evento ya visto: un
 * EventSource nuevo no puede mandar `Last-Event-ID`. */
export function streamUrlCorrida(corridaId: number, desde?: number): string {
  const base = `/api/admin/ingesta/cromo/corridas/${corridaId}/stream`;
  return desde ? `${base}?desde=${desde}` : base;
}

export interface OpcionesCorridaSse {
  /** Relee el estado de la corrida tras una caída de conexión. Si sigue EN_CURSO debe llamar de
   * nuevo a `conectar`; si terminó (p.ej. el worker la reconcilió a FALLIDA), no reconecta. */
  recargarEstado: () => Promise<void>;
  onInicio?: (data: Record<string, unknown>) => void;
  /** Cambio de fase de la corrida (sólo la ingesta lo emite). */
  onFase?: (data: Record<string, unknown>) => void;
  onPagina?: (data: Record<string, unknown>) => void;
  /** El RESUMEN cierra el stream. */
  onResumen?: (data: Record<string, unknown>) => void;
  /** Evento SSE `error` de negocio (con `data`): se informa y nada más. */
  onErrorNegocio?: (detalle: string) => void;
  /** Mismo evento `error` de negocio, con el JSON completo; sólo se llama si `data` es JSON válido. */
  onErrorDatos?: (data: Record<string, unknown>) => void;
}

export function useCorridaSse(opciones: OpcionesCorridaSse) {
  let eventSource: EventSource | null = null;
  let backoffMs = BACKOFF_INICIAL_MS;
  let reintentoTimer: ReturnType<typeof setTimeout> | null = null;
  let ultimoEventoId = 0;
  let corridaStream: number | null = null;
  // Se marca al desmontar: un fetch de `recargarEstado` en vuelo al desmontar volvía a llamar a
  // `conectar` y dejaba un EventSource huérfano.
  let desmontado = false;

  function cerrar(): void {
    eventSource?.close();
    eventSource = null;
  }

  function cancelarReintento(): void {
    if (reintentoTimer) clearTimeout(reintentoTimer);
    reintentoTimer = null;
  }

  /** Un evento ya visto se ignora (por si el servidor repite al reconectar) y se reanuda desde ahí. */
  function eventoNuevo(ev: Event): boolean {
    const id = Number.parseInt((ev as MessageEvent).lastEventId ?? '', 10);
    if (!Number.isFinite(id)) return true;
    if (id <= ultimoEventoId) return false;
    ultimoEventoId = id;
    backoffMs = BACKOFF_INICIAL_MS;
    return true;
  }

  function datos(ev: Event): Record<string, unknown> {
    return JSON.parse((ev as MessageEvent).data);
  }

  function conectar(corridaId: number): void {
    if (desmontado) return;
    cerrar();
    cancelarReintento();
    if (corridaStream !== corridaId) {
      corridaStream = corridaId;
      ultimoEventoId = 0;
    }
    const es = new EventSource(streamUrlCorrida(corridaId, ultimoEventoId || undefined));
    eventSource = es;
    es.addEventListener('inicio', (ev) => {
      if (eventoNuevo(ev)) opciones.onInicio?.(datos(ev));
    });
    es.addEventListener('fase', (ev) => {
      if (eventoNuevo(ev)) opciones.onFase?.(datos(ev));
    });
    es.addEventListener('pagina', (ev) => {
      if (eventoNuevo(ev)) opciones.onPagina?.(datos(ev));
    });
    es.addEventListener('resumen', (ev) => {
      if (!eventoNuevo(ev)) return;
      opciones.onResumen?.(datos(ev));
      cerrar();
    });
    // El tipo "error" lo usan DOS cosas: el evento SSE de negocio (MessageEvent con `data`) y la
    // caída de la conexión (Event sin `data`). El de negocio se informa y nada más; sólo la caída
    // real cierra y reintenta, con backoff y desde el último id.
    es.addEventListener('error', (ev) => {
      if (ev instanceof MessageEvent && ev.data) {
        if (!eventoNuevo(ev)) return;
        try {
          const data = JSON.parse(ev.data);
          opciones.onErrorNegocio?.(String(data.detalle ?? ev.data));
          opciones.onErrorDatos?.(data);
        } catch {
          opciones.onErrorNegocio?.(String(ev.data));
        }
        return;
      }
      // Cualquier error de conexión (también CONNECTING): se cierra y se relee el estado. Si la
      // corrida terminó sin RESUMEN, el servidor cierra el stream en cada reconexión y el
      // navegador reintentaría para siempre; `recargarEstado` ve el estado terminal y no reconecta.
      cerrar();
      const espera = backoffMs;
      backoffMs = Math.min(backoffMs * 2, BACKOFF_MAXIMO_MS);
      reintentoTimer = setTimeout(() => {
        if (!desmontado) void opciones.recargarEstado();
      }, espera);
    });
  }

  function detener(): void {
    cancelarReintento();
    cerrar();
  }

  onBeforeUnmount(() => {
    desmontado = true;
    detener();
  });

  return { conectar, detener };
}
