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

// Ordem de resolução: idioma guardado na sessão, idioma do navegador e, por
// fim, fallback em português.
export function detectInitialLanguage(): UiLanguage {
  try {
    const stored = window.sessionStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (isUiLanguage(stored)) {
      return stored;
    }
  } catch {
    // sessionStorage pode estar indisponível; usar o navegador/fallback.
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
    // Persistência apenas por melhor esforço.
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
