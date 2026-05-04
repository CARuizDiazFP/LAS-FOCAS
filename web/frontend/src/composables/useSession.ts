// Nombre de archivo: useSession.ts
// Ubicación de archivo: web/frontend/src/composables/useSession.ts
// Descripción: Composable singleton para estado de sesión y token CSRF del SPA unificado

import { ref } from 'vue';

interface SessionState {
  authenticated: boolean;
  username: string | null;
  role: string | null;
  csrf: string | null;
}

// Estado singleton a nivel módulo (compartido en toda la app)
const state = ref<SessionState>({
  authenticated: false,
  username: null,
  role: null,
  csrf: null,
});

let _fetched = false;

function _applyState(data: SessionState): void {
  state.value = data;
  // Compatibilidad con admin.ts que lee window.CSRF_TOKEN
  if (data.csrf) {
    (window as unknown as { CSRF_TOKEN: string }).CSRF_TOKEN = data.csrf;
  }
}

export function useSession() {
  const csrf = (): string => state.value.csrf ?? '';

  async function fetchSession(): Promise<SessionState> {
    const res = await fetch('/api/auth/session', { credentials: 'include' });
    if (res.ok) {
      const data: SessionState = await res.json();
      _applyState(data);
      _fetched = true;
    }
    return state.value;
  }

  async function ensureSession(): Promise<SessionState> {
    if (!_fetched) {
      return fetchSession();
    }
    return state.value;
  }

  function setSession(data: SessionState): void {
    _applyState(data);
    _fetched = true;
  }

  function clearSession(): void {
    state.value = { authenticated: false, username: null, role: null, csrf: null };
    _fetched = false;
  }

  return { state, csrf, fetchSession, ensureSession, setSession, clearSession };
}
