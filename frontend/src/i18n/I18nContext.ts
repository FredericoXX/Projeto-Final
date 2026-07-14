import { createContext } from 'react';
import type { TranslationKey, TranslationParams, UiLanguage } from './index';

export interface I18nContextValue {
  language: UiLanguage;
  setLanguage: (language: UiLanguage) => void;
  t: (key: TranslationKey, params?: TranslationParams) => string;
}

export const I18nContext = createContext<I18nContextValue | null>(null);
