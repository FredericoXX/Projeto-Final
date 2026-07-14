import type { ValidationIssue } from '../types/api';
import type { TranslationKey } from '../i18n';

// A typed error the whole app throws and renders. It never carries raw
// response bodies, tokens or headers — only a safe status/code/message.
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly validationIssues?: ValidationIssue[];

  constructor(
    status: number,
    code: string,
    message: string,
    validationIssues?: ValidationIssue[],
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.validationIssues = validationIssues;
  }
}

function isDomainError(detail: unknown): detail is { code: string; message: string } {
  return (
    typeof detail === 'object' &&
    detail !== null &&
    'code' in detail &&
    'message' in detail &&
    typeof (detail as { code: unknown }).code === 'string'
  );
}

function isValidationDetail(detail: unknown): detail is ValidationIssue[] {
  return Array.isArray(detail);
}

// Interprets the two documented backend error shapes plus anything else
// (HTML error pages, non-JSON, network) as a safe ApiError. Never surfaces the
// raw payload to the caller.
export async function parseApiError(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    const data: unknown = await response.json();
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      detail = (data as { detail: unknown }).detail;
    }
  } catch {
    // Non-JSON body (e.g. an HTML error page): keep detail undefined.
  }

  if (isDomainError(detail)) {
    return new ApiError(response.status, detail.code, detail.message);
  }
  if (isValidationDetail(detail)) {
    return new ApiError(
      response.status,
      'validation_error',
      'validation_error',
      detail,
    );
  }
  return new ApiError(response.status, 'unknown_error', 'unknown_error');
}

// Maps an error to a stable, localized translation key. The backend message
// is intentionally not shown verbatim for most cases so the UI stays
// consistent and never leaks internal detail.
export function errorTranslationKey(error: unknown): TranslationKey {
  if (!(error instanceof ApiError)) {
    return 'error.network';
  }
  switch (error.code) {
    case 'validation_error':
    case 'domain_validation_error':
      return 'error.validation';
    case 'resource_not_found':
      return 'error.notFound';
    case 'resource_conflict':
      return 'error.conflict';
    case 'service_unavailable':
      return 'error.generationUnavailable';
    case 'upstream_error':
      return 'error.generationFailed';
    default:
      break;
  }
  if (error.status === 404) return 'error.notFound';
  if (error.status === 409) return 'error.conflict';
  if (error.status === 422) return 'error.validation';
  if (error.status === 502) return 'error.generationFailed';
  if (error.status === 503) return 'error.generationUnavailable';
  return 'error.generic';
}
