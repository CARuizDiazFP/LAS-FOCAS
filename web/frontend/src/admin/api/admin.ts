// Nombre de archivo: admin.ts
// Ubicación de archivo: web/frontend/src/admin/api/admin.ts
// Descripción: Wrappers fetch para todos los endpoints del panel admin

const CSRF = (): string => (window as never as { CSRF_TOKEN: string }).CSRF_TOKEN ?? '';

function formBody(data: Record<string, string | number | boolean>): FormData {
  const fd = new FormData();
  fd.append('csrf_token', CSRF());
  for (const [k, v] of Object.entries(data)) {
    fd.append(k, String(v));
  }
  return fd;
}

// ─── Tipos ───────────────────────────────────────────────────────────────

export interface AdminUser {
  username: string;
  role: string;
}

export interface BaneosConfig {
  intervalo_horas: number;
  slack_channels: string;
  activo: boolean;
  hora_inicio: number | null;
  ultima_ejecucion: string | null;
  ultimo_error: string | null;
}

export interface WorkerHealth {
  status: string;
  intervalo_horas?: number;
  last_run?: string;
  last_error?: string | null;
  listener_activo?: boolean;
}

export interface ListenerConfig {
  activo: boolean;
  canal_id: string;
  ultimo_error: string | null;
}

// ─── Endpoints ───────────────────────────────────────────────────────────

/** Devuelve el usuario admin autenticado, lanza Error si no es admin. */
export async function getAdminMe(): Promise<AdminUser> {
  const res = await fetch('/api/admin/me', { credentials: 'include' });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json() as Promise<AdminUser>;
}

/** Crea un nuevo usuario. */
export async function createUser(
  username: string,
  password: string,
  role: string,
): Promise<void> {
  const res = await fetch('/api/admin/users', {
    method: 'POST',
    credentials: 'include',
    body: formBody({ username, password, role }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error ?? `Error ${res.status}`);
}

/** Cambia la contraseña del usuario autenticado. */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await fetch('/api/users/change-password', {
    method: 'POST',
    credentials: 'include',
    body: formBody({ current_password: currentPassword, new_password: newPassword }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error ?? `Error ${res.status}`);
}

/** Obtiene la configuración del worker de baneos. */
export async function getBaneosConfig(): Promise<BaneosConfig> {
  const res = await fetch('/api/admin/servicios/baneos/config', { credentials: 'include' });
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return res.json() as Promise<BaneosConfig>;
}

/** Guarda la configuración del worker de baneos. */
export async function saveBaneosConfig(
  intervaloHoras: number,
  slackChannels: string,
  activo: boolean,
  horaInicio: number | null,
): Promise<void> {
  const payload: Record<string, string | number | boolean> = {
    intervalo_horas: intervaloHoras,
    slack_channels: slackChannels,
    activo: activo ? 'on' : 'off',
    hora_inicio: horaInicio !== null ? horaInicio : '',
  };
  const res = await fetch('/api/admin/servicios/baneos', {
    method: 'POST',
    credentials: 'include',
    body: formBody(payload),
  });
  if (res.status === 303 || res.ok) return; // redirect = éxito
  const data = await res.json().catch(() => ({}));
  throw new Error((data as { error?: string }).error ?? `Error ${res.status}`);
}

/** Inicia el contenedor del worker si está detenido. */
export async function startWorker(): Promise<{ status: string; msg?: string; container_status?: string }> {
  const res = await fetch('/api/admin/servicios/baneos/worker/start', {
    method: 'POST',
    credentials: 'include',
    body: formBody({}),
  });
  const data = await res.json().catch(() => ({})) as { status?: string; msg?: string; container_status?: string; error?: string };
  if (!res.ok) throw new Error(data.error ?? `Error ${res.status}`);
  return data as { status: string; msg?: string; container_status?: string };
}

/** Dispara una ejecución manual inmediata del worker. */
export async function triggerManualNotification(): Promise<{ ok: boolean; msg?: string }> {
  const res = await fetch('/api/admin/servicios/baneos/trigger', {
    method: 'POST',
    credentials: 'include',
    body: formBody({}),
  });
  const data = await res.json().catch(() => ({})) as { ok?: boolean; msg?: string; error?: string };
  if (!res.ok) throw new Error(data.error ?? `Error ${res.status}`);
  return data as { ok: boolean; msg?: string };
}

/** Verifica el estado del worker de baneos. */
export async function getBaneosHealth(): Promise<WorkerHealth> {
  const res = await fetch('/api/admin/servicios/baneos/health', { credentials: 'include' });
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return res.json() as Promise<WorkerHealth>;
}

/** Devuelve la configuración del listener de ingresos. */
export async function getListenerConfig(): Promise<ListenerConfig> {
  const res = await fetch('/api/admin/servicios/baneos/listener', { credentials: 'include' });
  if (!res.ok) throw new Error(`Error ${res.status}`);
  return res.json() as Promise<ListenerConfig>;
}

/** Guarda la configuración del listener de ingresos. */
export async function saveListenerConfig(activo: boolean, canalId: string): Promise<void> {
  const res = await fetch('/api/admin/servicios/baneos/listener', {
    method: 'POST',
    credentials: 'include',
    body: formBody({ activo: activo ? 'on' : 'off', canal_id: canalId }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({})) as { error?: string };
    throw new Error(data.error ?? `Error ${res.status}`);
  }
}
