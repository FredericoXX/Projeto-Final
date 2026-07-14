import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  detectInitialLanguage,
  persistLanguage,
  translate,
  type TranslationKey,
  type TranslationParams,
  type UiLanguage,
} from './index';
import { I18nContext, type I18nContextValue } from './I18nContext';

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<UiLanguage>(detectInitialLanguage);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const setLanguage = useCallback((next: UiLanguage) => {
    persistLanguage(next);
    setLanguageState(next);
  }, []);

  const t = useCallback(
    (key: TranslationKey, params?: TranslationParams) => translate(language, key, params),
    [language],
  );

  const value = useMemo<I18nContextValue>(
    () => ({ language, setLanguage, t }),
    [language, setLanguage, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
