<!--
  Nombre de archivo: ChatTab.vue
  Ubicación de archivo: web/frontend/src/views/tabs/ChatTab.vue
  Descripción: Tab de chat HTTP con adjuntos, drag-and-drop y chips de sugerencia — columna centrada estilo Nocturne
-->
<template>
  <section class="chat-tab">
    <header class="chat-tab__header">
      <div>
        <span class="chat-tab__kicker">Asistente</span>
        <div class="chat-tab__heading-row">
          <h1>Home</h1>
          <p class="chat-tab__subtitle">Pedile informes, buscá servicios o adjuntá un Excel.</p>
        </div>
      </div>
      <span class="chat-tab__mcp-chip">MCP</span>
    </header>

    <hr class="noc-rule" />

    <div class="chat-tab__wrap">
      <div class="chat-tab__column">
        <div v-if="messages.length === 0" class="chat-tab__suggestions">
          <button
            v-for="suggestion in suggestions"
            :key="suggestion.text"
            type="button"
            class="chat-tab__suggestion"
            @click="useSuggestion(suggestion.text)"
          >
            <i :class="['ph', suggestion.icon]" aria-hidden="true"></i>
            {{ suggestion.text }}
          </button>
        </div>

        <div ref="logEl" class="chat-tab__log">
          <div v-for="(msg, i) in messages" :key="i" :class="['chat-tab__message', `is-${msg.role}`]">
            <span class="chat-tab__message-role">{{ msg.role === 'user' ? (username || 'vos') : 'asistente' }}</span>
            <p class="chat-tab__bubble">{{ msg.text }}</p>
          </div>
        </div>

        <div v-if="attachments.length > 0" class="chat-tab__attachments">
          <span v-for="(att, i) in attachments" :key="i" class="chat-tab__attachment-chip">
            <i class="ph ph-paperclip" aria-hidden="true"></i>
            <span>{{ att.name }}</span>
            <button type="button" class="chat-tab__attachment-remove" title="Quitar" @click="removeAttachment(i)">×</button>
          </span>
          <span class="chat-tab__attachments-note">Límite 15 MB por archivo</span>
        </div>

        <div
          class="chat-tab__dropzone"
          :class="{ 'is-dragging': isDragging }"
          @dragover.prevent="isDragging = true"
          @dragleave="isDragging = false"
          @drop.prevent="handleDrop"
        >
          <i class="ph ph-upload-simple" aria-hidden="true"></i>
          Arrastrá archivos o
          <button type="button" class="chat-tab__link" @click="fileInputEl?.click()">buscá en tu equipo</button>
        </div>
        <input ref="fileInputEl" type="file" multiple hidden @change="handleFileSelect" />

        <p v-if="statusText" :class="['chat-tab__status', { 'is-error': statusMode === 'error' }]">{{ statusText }}</p>

        <form class="chat-tab__composer" @submit.prevent="handleSubmit">
          <input v-model="inputText" name="text" type="text" placeholder="Escribí un mensaje" required />
          <button type="submit" class="btn primary chat-tab__send" :disabled="sending">
            <i class="ph ph-paper-plane-right" aria-hidden="true"></i>
            Enviar
          </button>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue';
import { useSession } from '../../composables/useSession';

interface ChatMessage { role: string; text: string }
interface Attachment { name: string; path: string; size: number }

const { csrf, state } = useSession();
const username = ref('');
username.value = state.value.username ?? '';

const messages = ref<ChatMessage[]>([]);
const inputText = ref('');
const statusText = ref('');
const statusMode = ref('');
const sending = ref(false);
const isDragging = ref(false);
const attachments = ref<Attachment[]>([]);
const logEl = ref<HTMLDivElement | null>(null);
const fileInputEl = ref<HTMLInputElement | null>(null);

const suggestions = [
  { text: 'Generar SLA de julio', icon: 'ph-file-text' },
  { text: 'Buscar servicio por cliente', icon: 'ph-magnifying-glass' },
  { text: 'Cámaras baneadas hoy', icon: 'ph-lock-key' },
  { text: 'Repetitividad del último mes', icon: 'ph-repeat' },
];

function useSuggestion(text: string): void {
  inputText.value = text;
  void handleSubmit();
}

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

<style scoped>
.chat-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.chat-tab__header {
  display: flex;
  align-items: flex-end;
  gap: 16px;
  padding: 22px 26px 0;
}

.chat-tab__kicker {
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--color-accent);
}

.chat-tab__heading-row {
  display: flex;
  align-items: flex-end;
  gap: 16px;
}

.chat-tab__heading-row h1 {
  font-size: 27px;
  margin: 3px 0 0;
}

.chat-tab__subtitle {
  margin: 0 0 4px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 52%, transparent);
}

.chat-tab__mcp-chip {
  margin-left: auto;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 10.5px;
  border: 1px solid var(--color-accent);
  color: var(--color-accent);
}

.chat-tab__wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 18px 26px 22px;
}

.chat-tab__column {
  width: 100%;
  max-width: 760px;
  margin-inline: auto;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chat-tab__suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.chat-tab__suggestion {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: var(--radius-pill);
  font-size: 11.5px;
  cursor: pointer;
  border: 1px solid var(--color-divider);
  background: transparent;
  color: color-mix(in srgb, var(--color-text) 66%, transparent);
}

.chat-tab__suggestion:hover {
  border-color: var(--color-accent);
}

.chat-tab__suggestion i {
  font-size: 13px;
}

.chat-tab__log {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 13px;
  padding: 4px 2px;
}

.chat-tab__message {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 80%;
}

.chat-tab__message.is-user {
  align-self: flex-end;
  align-items: flex-end;
}

.chat-tab__message-role {
  font-size: 9.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--color-neutral-500);
}

.chat-tab__message.is-user .chat-tab__message-role {
  color: var(--color-accent);
}

.chat-tab__bubble {
  margin: 0;
  padding: 9px 12px;
  border-radius: var(--radius-md);
  font-size: 13px;
  line-height: 1.5;
  text-wrap: pretty;
  background: var(--color-surface);
  color: color-mix(in srgb, var(--color-text) 88%, transparent);
}

.chat-tab__message.is-user .chat-tab__bubble {
  border: 1px solid var(--color-accent);
  color: var(--color-accent-200);
  background: color-mix(in srgb, var(--color-accent) 10%, transparent);
}

.chat-tab__attachments {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.chat-tab__attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: 4px;
  background: var(--color-surface);
}

.chat-tab__attachment-remove {
  background: transparent;
  border: 0;
  color: var(--color-neutral-500);
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0 2px;
}

.chat-tab__dropzone {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 13px;
  border: 1px dashed var(--color-neutral-700);
  border-radius: var(--radius-md);
  font-size: 12.5px;
  color: color-mix(in srgb, var(--color-text) 55%, transparent);
}

.chat-tab__dropzone.is-dragging,
.chat-tab__dropzone:hover {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.chat-tab__link {
  background: none;
  border: none;
  color: var(--color-accent);
  cursor: pointer;
  padding: 0;
  font: inherit;
}

.chat-tab__link:hover {
  text-decoration: underline;
}

.chat-tab__status {
  margin: 0;
  font-size: 11.5px;
  color: color-mix(in srgb, var(--color-text) 45%, transparent);
}

.chat-tab__status.is-error {
  color: var(--color-state-error);
}

.chat-tab__composer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-tab__composer input {
  flex: 1;
  min-height: 40px;
  padding: 6px 10px;
  font-size: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-md);
  color: var(--color-text);
  caret-color: var(--color-accent);
}

.chat-tab__composer input:focus-visible {
  border-color: var(--color-accent);
  outline-offset: 0;
}

.chat-tab__send {
  min-height: 40px;
}
</style>
