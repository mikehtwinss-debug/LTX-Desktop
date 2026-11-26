import axios, { type AxiosError } from 'axios';

import { notify } from './notify';
import { getCompanyId, getToken, setToken } from './session';

export type ApiErrorDetails = Record<string, unknown>;

/**
 * The only error type the API layer throws. `status` is the HTTP status (0 when no response was
 * received), `code` the machine-readable error key (`PERIOD_CLOSED`, `VALIDATION_ERROR`, ...),
 * `message` a Turkish text that can be shown to the user as is.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: ApiErrorDetails | null;

  constructor(status: number, code: string, message: string, details: ApiErrorDetails | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const UNEXPECTED_MESSAGE = 'Beklenmeyen bir hata oluştu.';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Used when the response body is not the JSON error shape (proxy errors, HTML error pages, ...). */
function fallbackError(status: number): ApiError {
  switch (status) {
    case 401:
      return new ApiError(status, 'UNAUTHORIZED', 'Oturumunuz sona erdi. Lütfen tekrar giriş yapın.');
    case 403:
      return new ApiError(status, 'FORBIDDEN', 'Bu işlem için yetkiniz yok.');
    case 404:
      return new ApiError(status, 'NOT_FOUND', 'Kayıt bulunamadı.');
    case 413:
      return new ApiError(status, 'PAYLOAD_TOO_LARGE', 'Gönderilen dosya çok büyük.');
    default:
      return status >= 500
        ? new ApiError(status, 'SERVER_ERROR', 'Sunucu hatası oluştu. Lütfen daha sonra tekrar deneyin.')
        : new ApiError(status, 'HTTP_ERROR', 'İşlem gerçekleştirilemedi.');
  }
}

/** Builds an ApiError from an HTTP status and a parsed response body. */
export function apiErrorFromResponse(status: number, body: unknown): ApiError {
  if (isRecord(body) && typeof body.code === 'string' && typeof body.message === 'string') {
    return new ApiError(status, body.code, body.message, isRecord(body.details) ? body.details : null);
  }
  return fallbackError(status);
}

async function parseJsonBlob(blob: Blob): Promise<unknown> {
  try {
    return JSON.parse(await blob.text());
  } catch {
    return null;
  }
}

/**
 * Converts anything thrown by a request into an ApiError. Cancelled requests are returned
 * untouched so that TanStack Query can recognise them.
 */
export async function normalizeError(error: unknown): Promise<unknown> {
  if (error instanceof ApiError || axios.isCancel(error)) {
    return error;
  }
  if (!axios.isAxiosError(error)) {
    return new ApiError(0, 'UNEXPECTED_ERROR', UNEXPECTED_MESSAGE);
  }
  const response = error.response;
  if (!response) {
    return new ApiError(0, 'NETWORK_ERROR', 'Sunucuya ulaşılamıyor. Bağlantınızı kontrol edip tekrar deneyin.');
  }
  // Downloads are requested as blobs, so their error bodies arrive as JSON blobs.
  const body: unknown = response.data instanceof Blob ? await parseJsonBlob(response.data) : response.data;
  return apiErrorFromResponse(response.status, body);
}

/** Text to show to the user for any thrown value. */
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : UNEXPECTED_MESSAGE;
}

export type QueryValue = string | number | boolean | null | undefined | readonly (string | number)[];
export type QueryParams = Record<string, QueryValue>;

/** Drops empty values so that optional filters never reach the server as `field=`. */
export function cleanParams(params: QueryParams): Record<string, string | number | boolean | readonly (string | number)[]> {
  const cleaned: Record<string, string | number | boolean | readonly (string | number)[]> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') {
      continue;
    }
    if (typeof value === 'object' && value.length === 0) {
      continue;
    }
    cleaned[key] = value;
  }
  return cleaned;
}

/** Axios instance for the backend. Prefer the typed helpers below; use it directly for special cases. */
export const api = axios.create({
  baseURL: '/api',
  // Arrays are sent as repeated keys (`status=A&status=B`).
  paramsSerializer: { indexes: null },
});

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`);
    const companyId = getCompanyId();
    // A caller may address another company explicitly (probing it before a company switch).
    if (companyId !== null && !config.headers.has('X-Company-Id')) {
      config.headers.set('X-Company-Id', String(companyId));
    }
  }
  return config;
});

/** True for a 401 that means "not signed in any more" rather than "wrong password". */
export function isSessionExpiry(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401 && error.code !== 'INVALID_CREDENTIALS';
}

function sentWithCurrentToken(error: unknown): boolean {
  const token = getToken();
  const sent = (error as AxiosError).config?.headers?.get('Authorization');
  return token !== null && sent === `Bearer ${token}`;
}

api.interceptors.response.use(undefined, async (error: unknown) => {
  const normalized = await normalizeError(error);
  // A rejected token ends the session: dropping it makes the auth provider clear its state and the
  // route guards redirect to the login page. Wrong credentials (login, password change) and replies
  // to requests sent with an older token are not session expiry.
  if (isSessionExpiry(normalized) && sentWithCurrentToken(error)) {
    setToken(null);
    notify.warning('Oturumunuz sona erdi. Lütfen tekrar giriş yapın.', 'session-expired');
  }
  throw normalized;
});

export type EntityId = number | string;

/** The list contract: `GET <endpoint>?page=&page_size=&sort=&q=&<field>=<value>`. */
export interface ListParams extends QueryParams {
  page?: number;
  page_size?: number;
  /** Sort name, prefixed with `-` for descending order. */
  sort?: string;
  q?: string;
}

export interface ListResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export async function apiGet<T>(url: string, params?: QueryParams, signal?: AbortSignal): Promise<T> {
  const response = await api.get<T>(url, { params: params && cleanParams(params), signal });
  return response.data;
}

export async function apiPost<T>(url: string, body?: unknown): Promise<T> {
  const response = await api.post<T>(url, body);
  return response.data;
}

export function getList<T>(endpoint: string, params?: ListParams, signal?: AbortSignal): Promise<ListResult<T>> {
  return apiGet<ListResult<T>>(endpoint, params, signal);
}

export function getOne<T>(endpoint: string, id: EntityId, signal?: AbortSignal): Promise<T> {
  return apiGet<T>(`${endpoint}/${id}`, undefined, signal);
}

export function create<T>(endpoint: string, payload: unknown): Promise<T> {
  return apiPost<T>(endpoint, payload);
}

/** Full update; versioned resources expect the current `version` in the payload (409 `STALE_DATA`). */
export async function update<T>(endpoint: string, id: EntityId, payload: unknown): Promise<T> {
  const response = await api.put<T>(`${endpoint}/${id}`, payload);
  return response.data;
}

export async function remove(endpoint: string, id: EntityId): Promise<void> {
  await api.delete(`${endpoint}/${id}`);
}

/** Extracts the filename from a `Content-Disposition` header (RFC 5987 `filename*` preferred). */
export function filenameFromDisposition(header: string | undefined): string | null {
  if (!header) {
    return null;
  }
  const extended = /filename\*\s*=\s*[^';]*'[^';]*'([^;]+)/i.exec(header);
  if (extended?.[1]) {
    try {
      return decodeURIComponent(extended[1].trim());
    } catch {
      // Malformed percent-encoding: fall back to the plain parameter.
    }
  }
  const plain = /filename\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]+))/i.exec(header);
  const name = plain?.[1]?.replace(/\\(.)/g, '$1') ?? plain?.[2]?.trim();
  return name || null;
}

function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // The browser reads the blob asynchronously after the click.
  window.setTimeout(() => URL.revokeObjectURL(href), 10_000);
}

/** Downloads a server-built file (PDF, Excel, attachment) and saves it under the name the server sent. */
export async function downloadFile(url: string, params?: QueryParams): Promise<void> {
  const response = await api.get<Blob>(url, { params: params && cleanParams(params), responseType: 'blob' });
  const disposition: unknown = response.headers['content-disposition'];
  const filename =
    filenameFromDisposition(typeof disposition === 'string' ? disposition : undefined) ??
    url.split('/').filter(Boolean).pop() ??
    'dosya';
  saveBlob(response.data, filename.replace(/[\\/]/g, '_'));
}
