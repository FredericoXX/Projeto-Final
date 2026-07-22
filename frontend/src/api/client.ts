import { ApiError, parseApiError } from './errors';
import { tokenStorage } from './token';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

// AuthProvider regista um handler para que um 401 limpe a sessão uma única vez,
// de forma centralizada, em vez de cada chamador tratar o erro.
type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  // Corpo JSON (serializado automaticamente) ou FormData (enviado sem alteração
  // para o navegador definir o delimitador multipart).
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
    // Nunca definir Content-Type para FormData: o navegador adiciona o delimitador.
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
    // Falha de rede: nunca expor o objeto de erro subjacente.
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

// Download binário autenticado (por exemplo, um documento). Devolve um Blob
// para criar um URL de objeto temporário sem um link desprotegido.
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
