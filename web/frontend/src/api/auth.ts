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

import { request, requestJson } from './client';

export async function getSession(): Promise<SessionData> {
  const res = await request('/api/auth/session', { throwOnError: false });
  if (!res.ok) return { authenticated: false, username: null, role: null, csrf: null };
  return res.json() as Promise<SessionData>;
}

export async function login(username: string, password: string): Promise<LoginResult> {
  return requestJson<LoginResult>('/api/auth/login', {
    method: 'POST',
    json: { username, password },
  });
}

export async function logout(): Promise<void> {
  await request('/api/auth/logout', { method: 'POST', throwOnError: false });
}
