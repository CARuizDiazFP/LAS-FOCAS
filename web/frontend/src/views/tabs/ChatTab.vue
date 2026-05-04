<!--
  Nombre de archivo: ChatTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/ChatTab.vue
  Descripción: Tab de chat HTTP con adjuntos y drag-and-drop — migrado desde panel.js
-->
<template>
  <article class="card">
    <header class="card-header">
      <h1>Asistente conversacional</h1>
      <span class="badge">MCP</span>
    </header>
    <div class="chat">
      <div :class="['chat-status', statusMode]">{{ statusText }}</div>
      <div ref="logEl" class="chat-log">
        <div
          v-for="(msg, i) in messages"
          :key="i"
          :class="['msg', msg.role]"
        >{{ msg.text }}</div>
      </div>
      <div v-if="attachments.length > 0" class="chat-attachments active">
        <span
          v-for="(att, i) in attachments"
          :key="i"
          class="attachment-chip"
        >
          <span>{{ att.name }}</span>
          <button class="remove-attachment" title="Quitar" @click="removeAttachment(i)">×</button>
        </span>
      </div>
      <div
        class="chat-dropzone"
        :class="{ dragging: isDragging }"
        @dragover.prevent="isDragging = true"
        @dragleave="isDragging = false"
        @drop.prevent="handleDrop"
      >
        Arrastrá archivos o
        <button type="button" class="link-button" @click="fileInputEl?.click()">buscá en tu equipo</button>
        <small class="muted">Límite 15 MB por archivo</small>
      </div>
      <input ref="fileInputEl" type="file" multiple hidden @change="handleFileSelect" />
      <form class="chat-form" @submit.prevent="handleSubmit">
        <input v-model="inputText" name="text" type="text" placeholder="Escribí un mensaje" required />
        <button type="submit" class="btn primary" :disabled="sending">Enviar</button>
      </form>
    </div>
  </article>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue';
import { useSession } from '../../composables/useSession';

interface ChatMessage { role: string; text: string }
interface Attachment { name: string; path: string; size: number }

const { csrf } = useSession();
const messages = ref<ChatMessage[]>([]);
const inputText = ref('');
const statusText = ref('');
const statusMode = ref('');
const sending = ref(false);
const isDragging = ref(false);
const attachments = ref<Attachment[]>([]);
const logEl = ref<HTMLDivElement | null>(null);
const fileInputEl = ref<HTMLInputElement | null>(null);

function setStatus(text: string, mode = '') {
  statusText.value = text;
  statusMode.value = mode;
}

function scrollBottom() {
  nextTick(() => { if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight; });
}

function addMessage(role: string, text: string) {
  messages.value.push({ role, text });
  scrollBottom();
}

function removeAttachment(i: number) {
  attachments.value.splice(i, 1);
}

async function uploadFile(file: File) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('csrf_token', csrf());
  setStatus(`Subiendo ${file.name}...`);
  try {
    const res = await fetch('/api/chat/uploads', { method: 'POST', body: fd, credentials: 'include' });
    const j = await res.json();
    if (!res.ok) throw new Error(j.error ?? 'Error');
    attachments.value.push({ name: j.name, path: j.path, size: j.size });
    setStatus('');
  } catch (e: unknown) {
    setStatus(`Error subiendo ${file.name}: ${e instanceof Error ? e.message : String(e)}`, 'error');
  }
}

async function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement;
  const files = Array.from(input.files ?? []);
  for (const f of files) await uploadFile(f);
  input.value = '';
}

async function handleDrop(e: DragEvent) {
  isDragging.value = false;
  const files = Array.from(e.dataTransfer?.files ?? []);
  for (const f of files) await uploadFile(f);
}

async function handleSubmit() {
  const text = inputText.value.trim();
  if (!text || sending.value) return;
  addMessage('user', text);
  inputText.value = '';
  sending.value = true;
  setStatus('Enviando...');
  const body = new URLSearchParams();
  body.set('text', text);
  body.set('csrf_token', csrf());
  try {
    const res = await fetch('/api/chat/message', {
      method: 'POST',
      body,
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });
    const j = await res.json();
    if (!res.ok) throw new Error(j.error ?? 'Error');
    addMessage('assistant', j.reply ?? '(sin respuesta)');
    setStatus('');
  } catch (e: unknown) {
    setStatus(`Error: ${e instanceof Error ? e.message : String(e)}`, 'error');
  } finally {
    sending.value = false;
  }
}
</script>
