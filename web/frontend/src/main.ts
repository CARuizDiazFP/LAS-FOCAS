const app = document.getElementById('app') as HTMLDivElement;

app.innerHTML = `
  <div class="topbar">
    <div class="brand">LAS-FOCAS</div>
    <nav class="actions">
      <button class="btn">SLA</button>
      <button class="btn">Repetitividad</button>
      <button class="btn">Comparador FO</button>
      <button class="btn">Modo oscuro</button>
      <a class="btn" href="/logout">Salir</a>
    </nav>
  </div>
  <main class="container">
    <section class="panel">
      <h1>Panel</h1>
      <div class="chat">
        <div id="chat-log" class="chat-log"></div>
        <form id="chat-form" class="chat-form">
          <input id="chat-input" name="text" type="text" placeholder="Escribí un mensaje" required />
          <button type="submit" class="btn primary">Enviar</button>
        </form>
      </div>
    </section>
  </main>
`;

const form = document.getElementById('chat-form') as HTMLFormElement;
const input = document.getElementById('chat-input') as HTMLInputElement;
const log = document.getElementById('chat-log') as HTMLDivElement;

function append(role: 'user' | 'assistant', text: string) {
  const el = document.createElement('div');
  el.className = 'msg ' + role;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  append('user', text);
  input.value = '';
  try {
    const API_BASE = (window as any).API_BASE || 'http://localhost:8080';
    const CSRF = (window as any).CSRF_TOKEN || '';
    const body = new FormData();
    body.append('text', text);
    if (CSRF) body.append('csrf_token', CSRF);
    const res = await fetch(`${API_BASE}/api/chat/message`, { method: 'POST', body, credentials: 'include' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    append('assistant', `${data.reply} (Intent: ${data.intent} • ${Math.round((data.confidence||0)*100)}%)`);
  } catch (err) {
    append('assistant', 'Ocurrió un error al enviar el mensaje.');
    console.error(err);
  }
});
