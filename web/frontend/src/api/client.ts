// Nombre de archivo: client.ts
// Ubicación de archivo: web/frontend/src/api/client.ts
// Descripción: Cliente HTTP compartido del SPA con credenciales, CSRF y manejo uniforme de errores

type JsonPrimitive = string | number | boolean | null;
type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue | undefined };

export interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  headers?: HeadersInit;
  json?: Record<string, JsonValue>;
  formData?: FormData;
  body?: BodyInit | null;
  csrf?: boolean;
  credentials?: RequestCredentials;
  throwOnError?: boolean;
  /** Permite cancelar el request (cierre de modal, cambio de selección, timeout de cliente). */
  signal?: AbortSignal;
}

export class ApiError extends Error {
  status: number;
  payload?: unknown;

  constructor(message: string, status: number, payload?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

let csrfToken: string | null = null;

function legacyWindow(): Window & { CSRF_TOKEN?: string } {
  return window as Window & { CSRF_TOKEN?: string };
}

function syncLegacyCsrfToken(token: string | null): void {
  const target = legacyWindow();
  if (token) {
    target.CSRF_TOKEN = token;
    return;
  }
  delete target.CSRF_TOKEN;
}

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
  syncLegacyCsrfToken(token);
}

export function clearCsrfToken(): void {
  setCsrfToken(null);
}

export function getCsrfToken(): string {
  return csrfToken ?? legacyWindow().CSRF_TOKEN ?? '';
}

function cloneFormData(source: FormData): FormData {
  const next = new FormData();
  for (const [key, value] of source.entries()) {
    next.append(key, value);
  }
  return next;
}

function withCsrfJson(payload: Record<string, JsonValue>): Record<string, JsonValue> {
  return {
    ...payload,
    csrf_token: getCsrfToken(),
  };
}

function withCsrfFormData(formData: FormData): FormData {
  const next = cloneFormData(formData);
  next.set('csrf_token', getCsrfToken());
  return next;
}

async function readErrorPayload(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    return response.json().catch(() => null);
  }
  return response.text().catch(() => null);
}

function errorMessage(status: number, payload: unknown): string {
  if (payload && typeof payload === 'object') {
    const candidate = payload as { error?: unknown; detail?: unknown; message?: unknown };
    for (const value of [candidate.error, candidate.detail, candidate.message]) {
      if (typeof value === 'string' && value.trim().length > 0) {
        return value;
      }
    }
  }
  if (typeof payload === 'string' && payload.trim().length > 0) {
    return payload;
  }
  return `Error ${status}`;
}

export async function request(url: string, options: ApiRequestOptions = {}): Promise<Response> {
  const {
    method = 'GET',
    headers,
    json,
    formData,
    body,
    csrf = false,
    credentials = 'include',
    throwOnError = true,
    signal,
  } = options;

  const nextHeaders = new Headers(headers);
  let nextBody: BodyInit | null | undefined = body;

  if (formData) {
    nextBody = csrf ? withCsrfFormData(formData) : cloneFormData(formData);
  } else if (json) {
    nextHeaders.set('Content-Type', 'application/json');
    nextBody = JSON.stringify(csrf ? withCsrfJson(json) : json);
  }

  const response = await fetch(url, {
    method,
    headers: nextHeaders,
    body: nextBody,
    credentials,
    signal,
  });

  if (!response.ok && throwOnError) {
    const payload = await readErrorPayload(response);
    throw new ApiError(errorMessage(response.status, payload), response.status, payload);
  }

  return response;
}

export async function requestJson<T>(url: string, options: ApiRequestOptions = {}): Promise<T> {
  const response = await request(url, options);
  return response.json() as Promise<T>;
}

/** Dispara la descarga de un blob ya obtenido. Revoca el objectURL para no filtrar memoria. */
export function saveBlob(blob: Blob, filename: string): void {
  const blobUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');

  anchor.href = blobUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(blobUrl);
}

/**
 * Descarga un archivo del backend y devuelve el nombre que se usó.
 *
 * Hermano de `requestJson`: vive acá y no en un composable porque es TRANSPORTE, no dominio.
 * Antes de existir había cinco copias del mismo patrón blob+anchor+revoke repartidas por el SPA
 * (`useTracking`, `useCiena` y tres inline en `InfraTab.vue`); el requisito no es consolidarlas
 * todas de golpe, es que el código nuevo no agregue la sexta.
 *
 * Reusa `request()`, así que hereda credenciales, CSRF, `signal` y el `ApiError` con payload
 * parseado — incluido el caso "éxito en text/plain, error en application/json".
 */
export async function requestDownload(
  url: string,
  options: ApiRequestOptions & { fallbackFilename?: string } = {},
): Promise<string> {
  const { fallbackFilename = 'descarga.txt', ...resto } = options;
  const response = await request(url, {
    ...resto,
    headers: new Headers({ Accept: 'text/plain, application/octet-stream', ...(resto.headers ?? {}) }),
  });

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') ?? '';
  const match = disposition.match(/filename="(.+?)"/);
  const filename = match ? match[1] : fallbackFilename;

  saveBlob(blob, filename);
  return filename;
}

export function createFormData(
  values: Record<string, string | number | boolean | null | undefined>,
  includeCsrf = true,
): FormData {
  const formData = new FormData();
  for (const [key, value] of Object.entries(values)) {
    if (value === undefined || value === null) {
      continue;
    }
    formData.append(key, String(value));
  }
  if (includeCsrf) {
    formData.append('csrf_token', getCsrfToken());
  }
  return formData;
}