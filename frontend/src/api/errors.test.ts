import { describe, expect, it } from 'vitest';
import { ApiError, errorTranslationKey, parseApiError } from './errors';

describe('parseApiError', () => {
  it('reads a domain error', async () => {
    const response = new Response(
      JSON.stringify({ detail: { code: 'resource_not_found', message: 'missing' } }),
      { status: 404, headers: { 'content-type': 'application/json' } },
    );
    const error = await parseApiError(response);
    expect(error.status).toBe(404);
    expect(error.code).toBe('resource_not_found');
  });

  it('reads a validation error list', async () => {
    const response = new Response(
      JSON.stringify({ detail: [{ loc: ['body'], msg: 'x', type: 'y' }] }),
      { status: 422, headers: { 'content-type': 'application/json' } },
    );
    const error = await parseApiError(response);
    expect(error.code).toBe('validation_error');
    expect(error.validationIssues).toHaveLength(1);
  });

  it('falls back to unknown_error for unexpected bodies', async () => {
    const response = new Response('boom', { status: 500 });
    const error = await parseApiError(response);
    expect(error.code).toBe('unknown_error');
  });
});

describe('errorTranslationKey', () => {
  it('maps non-ApiError to a network message', () => {
    expect(errorTranslationKey(new Error('x'))).toBe('error.network');
  });

  it('maps known codes and statuses', () => {
    expect(errorTranslationKey(new ApiError(404, 'resource_not_found', ''))).toBe('error.notFound');
    expect(errorTranslationKey(new ApiError(409, 'resource_conflict', ''))).toBe('error.conflict');
    expect(errorTranslationKey(new ApiError(422, 'validation_error', ''))).toBe('error.validation');
    expect(errorTranslationKey(new ApiError(503, 'service_unavailable', ''))).toBe(
      'error.generationUnavailable',
    );
    expect(errorTranslationKey(new ApiError(502, 'upstream_error', ''))).toBe(
      'error.generationFailed',
    );
    expect(errorTranslationKey(new ApiError(500, 'weird', ''))).toBe('error.generic');
  });
});
