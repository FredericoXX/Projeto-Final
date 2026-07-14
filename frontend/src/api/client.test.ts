import { describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '../test/server';
import { API } from '../test/handlers';
import { apiRequest, setUnauthorizedHandler } from './client';
import { ApiError } from './errors';
import { tokenStorage } from './token';

describe('apiRequest', () => {
  it('calls the configured base URL', async () => {
    let seenUrl = '';
    server.use(
      http.get(`${API}/ping`, ({ request }) => {
        seenUrl = request.url;
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiRequest('/ping');
    expect(seenUrl).toBe('http://localhost/api/v1/ping');
  });

  it('adds the Authorization header when a token exists', async () => {
    tokenStorage.set('secret-token');
    let authHeader: string | null = null;
    server.use(
      http.get(`${API}/whoami`, ({ request }) => {
        authHeader = request.headers.get('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiRequest('/whoami');
    expect(authHeader).toBe('Bearer secret-token');
  });

  it('omits the Authorization header without a token', async () => {
    let hasAuth = true;
    server.use(
      http.get(`${API}/anon`, ({ request }) => {
        hasAuth = request.headers.has('authorization');
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiRequest('/anon');
    expect(hasAuth).toBe(false);
  });

  it('serializes a JSON body with a JSON content type', async () => {
    let contentType: string | null = null;
    let received: unknown;
    server.use(
      http.post(`${API}/echo`, async ({ request }) => {
        contentType = request.headers.get('content-type');
        received = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    await apiRequest('/echo', { method: 'POST', body: { hello: 'world' } });
    expect(contentType).toContain('application/json');
    expect(received).toEqual({ hello: 'world' });
  });

  it('sends FormData without setting Content-Type manually', async () => {
    let contentType = '';
    server.use(
      http.post(`${API}/upload`, ({ request }) => {
        contentType = request.headers.get('content-type') ?? '';
        return HttpResponse.json({ ok: true });
      }),
    );
    const form = new FormData();
    form.append('file', new File(['data'], 'a.txt', { type: 'text/plain' }));
    await apiRequest('/upload', { method: 'POST', body: form });
    // The browser/undici sets multipart with a boundary; we never set it.
    expect(contentType).toContain('multipart/form-data');
    expect(contentType).toContain('boundary=');
  });

  it('handles an empty 204 response', async () => {
    server.use(http.delete(`${API}/item`, () => new HttpResponse(null, { status: 204 })));
    await expect(apiRequest('/item', { method: 'DELETE' })).resolves.toBeUndefined();
  });

  it('parses a domain error shape', async () => {
    server.use(
      http.get(`${API}/conflict`, () =>
        HttpResponse.json({ detail: { code: 'resource_conflict', message: 'nope' } }, { status: 409 }),
      ),
    );
    await expect(apiRequest('/conflict')).rejects.toMatchObject({
      status: 409,
      code: 'resource_conflict',
    });
  });

  it('parses a Pydantic 422 error shape', async () => {
    server.use(
      http.post(`${API}/validate`, () =>
        HttpResponse.json(
          { detail: [{ loc: ['body', 'query'], msg: 'too short', type: 'value_error' }] },
          { status: 422 },
        ),
      ),
    );
    try {
      await apiRequest('/validate', { method: 'POST', body: {} });
      throw new Error('should have thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.status).toBe(422);
      expect(apiError.code).toBe('validation_error');
      expect(apiError.validationIssues).toHaveLength(1);
    }
  });

  it('handles a non-JSON error body safely', async () => {
    server.use(
      http.get(`${API}/html`, () =>
        new HttpResponse('<html>Internal Server Error</html>', {
          status: 500,
          headers: { 'content-type': 'text/html' },
        }),
      ),
    );
    await expect(apiRequest('/html')).rejects.toMatchObject({ status: 500, code: 'unknown_error' });
  });

  it('clears the token and notifies on 401', async () => {
    tokenStorage.set('to-be-cleared');
    const onUnauthorized = vi.fn();
    setUnauthorizedHandler(onUnauthorized);
    server.use(
      http.get(`${API}/secure`, () =>
        HttpResponse.json({ detail: { code: 'x', message: 'x' } }, { status: 401 }),
      ),
    );
    await expect(apiRequest('/secure')).rejects.toMatchObject({ status: 401 });
    expect(tokenStorage.get()).toBeNull();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
    setUnauthorizedHandler(null);
  });

  it('supports AbortSignal', async () => {
    server.use(
      http.get(`${API}/slow`, async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return HttpResponse.json({ ok: true });
      }),
    );
    const controller = new AbortController();
    const promise = apiRequest('/slow', { signal: controller.signal });
    controller.abort();
    await expect(promise).rejects.toThrow();
  });

  it('never logs the token', async () => {
    tokenStorage.set('super-secret-token');
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    server.use(http.get(`${API}/ping2`, () => HttpResponse.json({ ok: true })));
    await apiRequest('/ping2');
    const logged = [...logSpy.mock.calls, ...errorSpy.mock.calls].flat().join(' ');
    expect(logged).not.toContain('super-secret-token');
    logSpy.mockRestore();
    errorSpy.mockRestore();
  });
});
