// Nombre de archivo: useFoMonitorPolling.ts
// Ubicación de archivo: web/frontend/src/composables/useFoMonitorPolling.ts
// Descripción: Polling periódico (30 s por defecto) que se pausa con la pestaña oculta y cancela el request en vuelo

import { onBeforeUnmount, onMounted } from 'vue';

export function useFoMonitorPolling(tarea: (signal: AbortSignal) => Promise<void>, intervaloMs = 30_000) {
  let timer: number | undefined;
  let controlador: AbortController | null = null;

  async function ejecutar(): Promise<void> {
    controlador?.abort();
    controlador = new AbortController();
    try {
      await tarea(controlador.signal);
    } catch (err) {
      if ((err as Error).name !== 'AbortError') console.warn('fo-monitor polling', err);
    }
  }

  function programar(): void {
    window.clearInterval(timer);
    timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void ejecutar();
    }, intervaloMs);
  }

  function alCambiarVisibilidad(): void {
    if (document.visibilityState === 'visible') void ejecutar();
  }

  onMounted(() => {
    void ejecutar();
    programar();
    document.addEventListener('visibilitychange', alCambiarVisibilidad);
  });

  onBeforeUnmount(() => {
    window.clearInterval(timer);
    controlador?.abort();
    document.removeEventListener('visibilitychange', alCambiarVisibilidad);
  });

  return { refrescar: ejecutar };
}
