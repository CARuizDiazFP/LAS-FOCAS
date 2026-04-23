// Nombre de archivo: main.ts
// Ubicación de archivo: web/frontend/src/main.ts
// Descripción: Cliente Vite para el panel web (chat MCP con adjuntos y reconexión)

type StatusMode = 'info' | 'success' | 'warn' | 'error';

interface ChatAttachment {
  name: string;
  path: string;
  size: number;
  content_type?: string | null;
}

interface ChatHistoryEntry {
  id?: number;
  role?: string;
  content?: string;
  attachments?: ChatAttachment[] | null;
  error_code?: string | null;
  created_at?: string | null;
}

interface ChatEventPayload {
  type: string;
  content?: string;
  messages?: ChatHistoryEntry[];
  metadata?: Record<string, unknown>;
}

declare global {
  interface Window {
    CSRF_TOKEN?: string;
  }
}

const chatForm = document.getElementById('chat-form') as HTMLFormElement | null;
const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
const chatLog = document.getElementById('chat-log') as HTMLDivElement | null;
const chatStatus = document.getElementById('chat-status') as HTMLDivElement | null;
const chatAttachments = document.getElementById('chat-attachments') as HTMLDivElement | null;
const chatDropzone = document.getElementById('chat-dropzone') as HTMLDivElement | null;
const browseButton = document.getElementById('chat-attachment-browse') as HTMLButtonElement | null;
const chatFileInput = document.getElementById('chat-attachment-input') as HTMLInputElement | null;

if (!chatForm || !chatInput || !chatLog || !chatStatus) {
  // El chat no está presente en la página actual.
} else {
  const state = {
    ws: null as WebSocket | null,
    reconnectAttempts: 0,
    reconnectTimer: undefined as number | undefined,
    assistantBubble: null as HTMLDivElement | null,
    attachments: [] as ChatAttachment[],
    allowReconnect: true,
  };

  const scrollLogToBottom = () => {
    chatLog.scrollTop = chatLog.scrollHeight;
  };

  const setStatus = (text: string, mode: StatusMode = 'info') => {
    chatStatus.textContent = text;
    chatStatus.classList.remove('success', 'warn', 'error');
    if (mode !== 'info') {
      chatStatus.classList.add(mode);
    }
  };

  const clearAssistantBubble = () => {
    if (state.assistantBubble) {
      state.assistantBubble.classList.remove('streaming');
    }
    state.assistantBubble = null;
  };

  const appendMessage = (role: string, text: string, options?: { streaming?: boolean }) => {
    const element = document.createElement('div');
    element.className = `msg ${role}`;
    if (options?.streaming) {
      element.classList.add('streaming');
    }
    element.textContent = text;
    chatLog.appendChild(element);
    scrollLogToBottom();
    return element;
  };

  const appendLinksMessage = (result: Record<string, unknown>) => {
    const links = Object.entries(result)
      .filter(([, value]) => typeof value === 'string' && value)
      .map(([key, value]) => ({ key, href: value as string }));
    if (!links.length) {
      return;
    }
    const container = document.createElement('div');
    container.className = 'msg assistant';
    container.classList.add('attachments-note');
    const label = document.createElement('span');
    label.textContent = 'Resultados:';
    container.appendChild(label);
    links.forEach(({ key, href }) => {
      const link = document.createElement('a');
      link.href = href;
      link.textContent = key.toUpperCase();
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      container.appendChild(link);
    });
    chatLog.appendChild(container);
    scrollLogToBottom();
  };

  const ensureAssistantBubble = () => {
    if (!state.assistantBubble) {
      state.assistantBubble = appendMessage('assistant', '', { streaming: true });
    }
    return state.assistantBubble;
  };

  const renderHistory = (messages: ChatHistoryEntry[]) => {
    chatLog.innerHTML = '';
    messages
      .filter((message) => message.role !== 'tool')
      .forEach((message) => {
        appendMessage(message.role ?? 'assistant', message.content ?? '');
      });
    setStatus('Historial cargado', 'info');
  };

  const renderAttachments = () => {
    if (!chatAttachments) {
      return;
    }
    chatAttachments.innerHTML = '';
    if (!state.attachments.length) {
      chatAttachments.classList.remove('active');
      return;
    }
    chatAttachments.classList.add('active');
    state.attachments.forEach((attachment, index) => {
      const chip = document.createElement('div');
      chip.className = 'attachment-chip';
      const title = document.createElement('span');
      title.textContent = attachment.name;
      chip.appendChild(title);
      const removeButton = document.createElement('button');
      removeButton.type = 'button';
      removeButton.dataset.index = String(index);
      removeButton.className = 'remove-attachment';
      removeButton.title = 'Quitar adjunto';
      removeButton.textContent = '×';
      chip.appendChild(removeButton);
      chatAttachments.appendChild(chip);
    });
  };

  const removeAttachmentAt = (index: number) => {
    state.attachments.splice(index, 1);
    renderAttachments();
  };

  const resetAttachments = () => {
    state.attachments = [];
    renderAttachments();
  };

  const scheduleReconnect = () => {
    if (!state.allowReconnect) {
      return;
    }
    state.reconnectAttempts += 1;
    const cappedAttempts = Math.min(state.reconnectAttempts, 6);
    const baseDelay = Math.pow(2, cappedAttempts) * 400;
    const jitter = Math.random() * 250;
    const delay = Math.min(baseDelay + jitter, 15000);
    setStatus(`Reconectando en ${(delay / 1000).toFixed(1)}s`, 'warn');
    if (state.reconnectTimer) {
      window.clearTimeout(state.reconnectTimer);
    }
    state.reconnectTimer = window.setTimeout(connect, delay);
  };

  const handleEvent = (payload: ChatEventPayload) => {
    switch (payload.type) {
      case 'history_snapshot':
        if (Array.isArray(payload.messages)) {
          renderHistory(payload.messages);
        }
        break;
      case 'assistant_delta':
        if (!payload.content) {
          return;
        }
        const bubble = ensureAssistantBubble();
        bubble.textContent += payload.content;
        setStatus('Escribiendo...', 'info');
        break;
      case 'assistant_done':
        clearAssistantBubble();
        setStatus('Listo', 'success');
        if (payload.metadata && typeof payload.metadata === 'object') {
          const result = (payload.metadata as Record<string, unknown>).result as Record<string, unknown> | undefined;
          if (result) {
            appendLinksMessage(result);
          }
        }
        break;
      case 'error':
        clearAssistantBubble();
        setStatus(payload.content ?? 'Error en el chat', 'error');
        appendMessage('assistant', payload.content ?? 'Ocurrió un error.');
        break;
      default:
        console.warn('Evento WebSocket desconocido', payload);
    }
  };

  const connect = () => {
    state.allowReconnect = true;
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.close();
    }
    setStatus('Conectando...', 'info');
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/chat`);
    state.ws = socket;

    socket.onopen = () => {
      state.reconnectAttempts = 0;
      setStatus('Conectado', 'success');
    };

    socket.onmessage = (event: MessageEvent) => {
      try {
        const payload = JSON.parse(event.data) as ChatEventPayload;
        handleEvent(payload);
      } catch (error) {
        console.error('No se pudo parsear el mensaje del servidor', error);
      }
    };

    socket.onerror = () => {
      setStatus('Error de conexión', 'error');
    };

    socket.onclose = (event: CloseEvent) => {
      state.ws = null;
      clearAssistantBubble();
      if (event.code === 4401) {
        state.allowReconnect = false;
        setStatus('Sesión no autorizada. Iniciá sesión nuevamente.', 'error');
        appendMessage('assistant', 'Tu sesión expiró. Volvé a ingresar al panel.');
        return;
      }
      if (state.allowReconnect) {
        scheduleReconnect();
      }
    };
  };

  const sendMessage = (text: string) => {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
      setStatus('Sin conexión al chat', 'error');
      return;
    }
    const trimmed = text.trim();
    if (!trimmed && !state.attachments.length) {
      return;
    }
    appendMessage('user', trimmed || '[adjunto]');
    const payload = {
      type: 'user_message',
      content: trimmed,
      attachments: state.attachments,
    };
    state.ws.send(JSON.stringify(payload));
    chatInput.value = '';
    state.assistantBubble = null;
    setStatus('Enviando...', 'info');
    resetAttachments();
  };

  const uploadAttachment = async (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    if (window.CSRF_TOKEN) {
      formData.append('csrf_token', window.CSRF_TOKEN);
    }
    setStatus(`Subiendo ${file.name}...`, 'info');
    const response = await fetch('/api/chat/uploads', {
      method: 'POST',
      body: formData,
      credentials: 'include',
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || 'No se pudo subir el archivo');
    }
    const attachment: ChatAttachment = {
      name: data.name,
      path: data.path,
      size: data.size,
      content_type: data.content_type,
    };
    state.attachments.push(attachment);
    renderAttachments();
    setStatus(`Adjunto listo: ${attachment.name}`, 'success');
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files?.length) {
      return;
    }
    for (const file of Array.from(files)) {
      try {
        await uploadAttachment(file);
      } catch (error) {
        setStatus(error instanceof Error ? error.message : 'Fallo al subir adjunto', 'error');
        appendMessage('assistant', `No se pudo subir ${file.name}.`);
      }
    }
    if (chatFileInput) {
      chatFileInput.value = '';
    }
  };

  chatForm.addEventListener('submit', (event) => {
    event.preventDefault();
    sendMessage(chatInput.value);
  });

  chatAttachments?.addEventListener('click', (event) => {
    const target = event.target as HTMLElement;
    if (target.matches('button.remove-attachment')) {
      const index = Number.parseInt(target.dataset.index ?? '-1', 10);
      if (!Number.isNaN(index) && index >= 0) {
        removeAttachmentAt(index);
      }
    }
  });

  browseButton?.addEventListener('click', () => {
    chatFileInput?.click();
  });

  chatFileInput?.addEventListener('change', async () => {
    await handleFiles(chatFileInput.files);
  });

  chatDropzone?.addEventListener('dragover', (event) => {
    event.preventDefault();
    chatDropzone.classList.add('dragging');
  });

  chatDropzone?.addEventListener('dragleave', () => {
    chatDropzone.classList.remove('dragging');
  });

  chatDropzone?.addEventListener('drop', async (event) => {
    event.preventDefault();
    chatDropzone.classList.remove('dragging');
    const files = event.dataTransfer?.files;
    await handleFiles(files ?? null);
  });

  connect();
}

export {};
