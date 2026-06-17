// Nombre de archivo: useSession.ts
// Ubicación de archivo: web/frontend/src/composables/useSession.ts
// Descripción: Composable singleton para estado de sesión y token CSRF del SPA unificado

import { ref } from 'vue';
import { getSession, logout } from '../api/auth';
import { clearCsrfToken, setCsrfToken } from '../api/client';

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
  setCsrfToken(data.csrf);
}

export function useSession() {
  const csrf = (): string => state.value.csrf ?? '';

  async function fetchSession(): Promise<SessionState> {
    const data = await getSession();
    _applyState(data);
    _fetched = true;
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
    clearCsrfToken();
    _fetched = false;
  }

  async function logoutSession(): Promise<void> {
    try {
      await logout();
    } finally {
      clearSession();
    }
  }

  return { state, csrf, fetchSession, ensureSession, setSession, clearSession, logoutSession };
}
