// Nombre de archivo: useAdminNotifications.ts
// Ubicación de archivo: web/frontend/src/composables/useAdminNotifications.ts
// Descripción: Composable WebSocket genérico para notificaciones admin (/ws/admin-notifications), con una única conexión compartida por todos los componentes montados

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

// Backoff exponencial con jitter, tope en MAX_DELAY_MS.
function backoffDelay(attempt: number): number {
  const capped = Math.min(attempt, MAX_RECONNECT_ATTEMPTS);
  const delay = Math.min(Math.pow(2, capped) * BASE_DELAY_MS, MAX_DELAY_MS);
  return delay + Math.random() * JITTER_MS;
}

// Estado de módulo: una sola conexión por pestaña del navegador. Una vista y un panel anidado que
// llaman al composable a la vez (p. ej. el visor de inconsistencias con el análisis retroactivo del
// árbitro) comparten el socket; se cierra cuando se desmonta el último consumidor.
const handlers = new Map<string, Set<Handler>>();
let socket: WebSocket | null = null;
let consumers = 0;
let attempt = 0;
let allowReconnect = true;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function dispatch(message: AdminNotification): void {
  const forType = handlers.get(message.type);
  if (!forType) return;
  for (const handler of [...forType]) handler(message);
}

function scheduleReconnect(): void {
  if (!allowReconnect) return;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  const delay = backoffDelay(attempt);
  attempt += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, delay);
}

function connect(): void {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${window.location.host}/ws/admin-notifications`);
  socket = ws;

  // Los eventos de un socket ya reemplazado (cierre tardío tras un disconnect) se ignoran.
  ws.onopen = () => {
    if (ws === socket) attempt = 0;
  };
  ws.onmessage = (event: MessageEvent<string>) => {
    if (ws !== socket) return;
    try {
      dispatch(JSON.parse(event.data));
    } catch {
      // Mensaje no-JSON: se ignora, no es un error de conexión.
    }
  };
  ws.onclose = (event: CloseEvent) => {
    if (ws !== socket) return;
    socket = null;
    if (event.code === 4401) {
      allowReconnect = false;
      return;
    }
    scheduleReconnect();
  };
  ws.onerror = () => {
    ws.close();
  };
}

function disconnect(): void {
  allowReconnect = false;
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = null;
  const ws = socket;
  socket = null;
  ws?.close();
}

function acquire(): void {
  consumers += 1;
  // Sin socket ni reintento pendiente (primer consumidor, o un 4401 previo): conectar de nuevo.
  if (socket === null && reconnectTimer === null) {
    allowReconnect = true;
    attempt = 0;
    connect();
  }
}

function release(): void {
  consumers = Math.max(0, consumers - 1);
  if (consumers === 0) disconnect();
}

export function useAdminNotifications() {
  // Handlers registrados por este componente: se quitan al desmontarlo para que no sigan
  // recibiendo mensajes del socket compartido.
  const propios: Array<() => void> = [];

  onMounted(acquire);
  onUnmounted(() => {
    for (const quitar of propios.splice(0)) quitar();
    release();
  });

  function on(type: string, handler: Handler): () => void {
    if (!handlers.has(type)) handlers.set(type, new Set());
    handlers.get(type)!.add(handler);
    const quitar = () => {
      handlers.get(type)?.delete(handler);
    };
    propios.push(quitar);
    return quitar;
  }

  return { on };
}
