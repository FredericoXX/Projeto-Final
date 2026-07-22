import type { ValidationIssue } from '../types/api';
import type { TranslationKey } from '../i18n';

// Erro tipado lançado e apresentado em toda a aplicação. Nunca transporta
// corpos brutos, tokens ou cabeçalhos, apenas estado/código/mensagem seguros.
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

// Interpreta os dois formatos de erro documentados e qualquer outro conteúdo
// (HTML, não JSON ou rede) como ApiError seguro. Nunca expõe o payload bruto.
export async function parseApiError(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    const data: unknown = await response.json();
    if (typeof data === 'object' && data !== null && 'detail' in data) {
      detail = (data as { detail: unknown }).detail;
    }
  } catch {
    // Corpo não JSON (por exemplo, página HTML): manter detail indefinido.
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

// Mapeia um erro para uma chave de tradução localizada e estável. A mensagem do
// backend não é exibida literalmente na maioria dos casos, mantendo a interface
// consistente e sem expor detalhes internos.
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
