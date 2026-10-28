// Nombre de archivo: chat.ts
// Ubicación de archivo: web/frontend/src/api/chat.ts
// Descripción: Cliente frontend del chat (subida de adjuntos y envío de mensajes)

import { requestJson } from './client';

export interface AdjuntoChat {
  name: string;
  path: string;
  size: number;
}

export async function subirAdjuntoChat(file: File): Promise<AdjuntoChat> {
  const fd = new FormData();
  fd.append('file', file);
  return requestJson<AdjuntoChat>('/api/chat/uploads', { method: 'POST', formData: fd });
}

/** El endpoint espera `application/x-www-form-urlencoded`, por eso el cuerpo es `URLSearchParams` y no JSON. */
export async function enviarMensajeChat(text: string): Promise<{ reply?: string }> {
  return requestJson<{ reply?: string }>('/api/chat/message', {
    method: 'POST',
    body: new URLSearchParams({ text }),
    headers: { Accept: 'application/json' },
  });
}
