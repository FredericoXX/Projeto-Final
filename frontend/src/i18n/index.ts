import { pt } from './pt';
import { en } from './en';

export type UiLanguage = 'pt' | 'en';
export type TranslationKey = keyof typeof pt;
export type TranslationParams = Record<string, string | number>;

export const UI_LANGUAGES: UiLanguage[] = ['pt', 'en'];
export const LANGUAGE_STORAGE_KEY = 'institutional_assistant_ui_language';
const FALLBACK_LANGUAGE: UiLanguage = 'pt';

const dictionaries: Record<UiLanguage, Record<TranslationKey, string>> = { pt, en };

function isUiLanguage(value: string | null | undefined): value is UiLanguage {
  return value === 'pt' || value === 'en';
}

// Resolution order: language stored in session, then the browser language,
// then the Portuguese fallback.
export function detectInitialLanguage(): UiLanguage {
  try {
    const stored = window.sessionStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (isUiLanguage(stored)) {
      return stored;
    }
  } catch {
    // sessionStorage may be unavailable; fall through to browser/fallback.
  }
  const browser = navigator.language?.slice(0, 2).toLowerCase();
  if (isUiLanguage(browser)) {
    return browser;
  }
  return FALLBACK_LANGUAGE;
}

export function persistLanguage(language: UiLanguage): void {
  try {
    window.sessionStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Best-effort persistence only.
  }
}

export function translate(
  language: UiLanguage,
  key: TranslationKey,
  params?: TranslationParams,
): string {
  const template = dictionaries[language][key];
  if (!params) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = params[name];
    return value === undefined ? match : String(value);
  });
}
