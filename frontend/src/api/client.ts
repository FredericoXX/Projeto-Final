import { ApiError, parseApiError } from './errors';
import { tokenStorage } from './token';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

// The AuthProvider registers a handler so a 401 anywhere clears the session
// once, centrally, instead of every caller handling it.
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  // JSON body (serialized automatically) or FormData (sent as-is so the
  // browser sets the multipart boundary).
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

function buildHeaders(options: RequestOptions): { headers: Headers; body: BodyInit | undefined } {
  const headers = new Headers(options.headers);
  const token = tokenStorage.get();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let body: BodyInit | undefined;
  if (options.body instanceof FormData) {
    // Never set Content-Type for FormData: the browser adds the boundary.
    body = options.body;
  } else if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(options.body);
  }
  return { headers, body };
}

function handleUnauthorized(): ApiError {
  tokenStorage.clear();
  unauthorizedHandler?.();
  return new ApiError(401, 'unauthorized', 'unauthorized');
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { headers, body } = buildHeaders(options);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    // Network failure: never expose the underlying error object.
    throw new ApiError(0, 'network_error', 'network_error');
  }

  if (response.status === 401) {
    throw handleUnauthorized();
  }
  if (!response.ok) {
    throw await parseApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

// Authenticated binary download (e.g. document file). Returns a Blob so the
// caller can create a temporary object URL without an unprotected link.
export async function apiRequestBlob(path: string, options: RequestOptions = {}): Promise<Blob> {
  const { headers, body } = buildHeaders(options);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw error;
    }
    throw new ApiError(0, 'network_error', 'network_error');
  }

  if (response.status === 401) {
    throw handleUnauthorized();
  }
  if (!response.ok) {
    throw await parseApiError(response);
  }
  return response.blob();
}
