import type { UiLanguage } from '../i18n';

const LOCALES: Record<UiLanguage, string> = { pt: 'pt-PT', en: 'en-GB' };

export function formatDateTime(value: string | null | undefined, language: UiLanguage): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(LOCALES[language], {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

export function formatDate(value: string | null | undefined, language: UiLanguage): string {
  if (!value) return '—';
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return '—';
  const [, year, month, day] = match;
  const date = new Date(`${year}-${month}-${day}T00:00:00.000Z`);
  if (
    Number.isNaN(date.getTime()) ||
    date.getUTCFullYear() !== Number(year) ||
    date.getUTCMonth() + 1 !== Number(month) ||
    date.getUTCDate() !== Number(day)
  ) {
    return '—';
  }
  return new Intl.DateTimeFormat(LOCALES[language], {
    dateStyle: 'medium',
    timeZone: 'UTC',
  }).format(date);
}

export function formatFileSize(bytes: number | null | undefined, language: UiLanguage): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const formatted = new Intl.NumberFormat(LOCALES[language], {
    maximumFractionDigits: unitIndex === 0 ? 0 : 1,
  }).format(size);
  return `${formatted} ${units[unitIndex]}`;
}

// Apenas URLs http/https se tornam links; qualquer outro formato (javascript:,
// data:, relativo ou inválido) devolve null e nunca é renderizado como link.
export function safeHttpUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol === 'http:' || url.protocol === 'https:') {
      return url.toString();
    }
    return null;
  } catch {
    return null;
  }
}
