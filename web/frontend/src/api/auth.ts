// Nombre de archivo: auth.ts
// Ubicación de archivo: web/frontend/src/api/auth.ts
// Descripción: Wrappers fetch para endpoints de autenticación (/api/auth/*)

export interface SessionData {
  authenticated: boolean;
  username: string | null;
  role: string | null;
  csrf: string | null;
}

export interface LoginResult {
  ok: boolean;
  username?: string;
  role?: string;
  csrf?: string;
  error?: string;
}

export async function getSession(): Promise<SessionData> {
  const res = await fetch('/api/auth/session', { credentials: 'include' });
  if (!res.ok) return { authenticated: false, username: null, role: null, csrf: null };
  return res.json() as Promise<SessionData>;
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  });
  return res.json() as Promise<LoginResult>;
}

export async function logout(): Promise<void> {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
}
