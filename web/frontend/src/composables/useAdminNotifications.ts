// Nombre de archivo: useAdminNotifications.ts
// Ubicación de archivo: web/frontend/src/composables/useAdminNotifications.ts
// Descripción: Composable WebSocket genérico para notificaciones admin (/ws/admin-notifications)

import { onMounted, onUnmounted } from 'vue';

interface AdminNotification {
  type: string;
  [key: string]: unknown;
}

type Handler = (message: AdminNotification) => void;

const MAX_RECONNECT_ATTEMPTS = 6;
const BASE_DELAY_MS = 400;
const MAX_DELAY_MS = 15000;
const JITTER_MS = 250;

// Mismo patrón de backoff exponencial con jitter que web/frontend/src/chat/main.ts (único precedente
// de reconexión WS en este repo — no hay composable Vue previo que copiar).
function backoffDelay(attempt: number): number {
  const capped = Math.min(attempt, MAX_RECONNECT_ATTEMPTS);
  const delay = Math.min(Math.pow(2, capped) * BASE_DELAY_MS, MAX_DELAY_MS);
  return delay + Math.random() * JITTER_MS;
}

export function useAdminNotifications() {
  const handlers = new Map<string, Set<Handler>>();
  let socket: WebSocket | null = null;
  let attempt = 0;
  let allowReconnect = true;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  function dispatch(message: AdminNotification): void {
    const forType = handlers.get(message.type);
    if (!forType) return;
    for (const handler of forType) handler(message);
  }

  function scheduleReconnect(): void {
    if (!allowReconnect) return;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    const delay = backoffDelay(attempt);
    attempt += 1;
    reconnectTimer = setTimeout(connect, delay);
  }

  function connect(): void {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${window.location.host}/ws/admin-notifications`);

    socket.onopen = () => {
      attempt = 0;
    };
    socket.onmessage = (event: MessageEvent<string>) => {
      try {
        dispatch(JSON.parse(event.data));
      } catch {
        // Mensaje no-JSON: se ignora, no es un error de conexión.
      }
    };
    socket.onclose = (event: CloseEvent) => {
      if (event.code === 4401) {
        allowReconnect = false;
        return;
      }
      scheduleReconnect();
    };
    socket.onerror = () => {
      socket?.close();
    };
  }

  function disconnect(): void {
    allowReconnect = false;
    if (reconnectTimer) clearTimeout(reconnectTimer);
    socket?.close();
    socket = null;
  }

  onMounted(connect);
  onUnmounted(disconnect);

  function on(type: string, handler: Handler): () => void {
    if (!handlers.has(type)) handlers.set(type, new Set());
    handlers.get(type)!.add(handler);
    return () => handlers.get(type)?.delete(handler);
  }

  return { on };
}
