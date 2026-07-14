import { useTranslation } from '../../i18n/useTranslation';
import { UI_LANGUAGES, type UiLanguage } from '../../i18n';

export function LanguageSelector() {
  const { language, setLanguage, t } = useTranslation();
  const labels: Record<UiLanguage, string> = {
    pt: t('lang.pt'),
    en: t('lang.en'),
  };
  return (
    <label className="checkbox-field">
      <span className="visually-hidden">{t('lang.select')}</span>
      <select
        className="select"
        aria-label={t('lang.select')}
        value={language}
        onChange={(event) => setLanguage(event.target.value as UiLanguage)}
      >
        {UI_LANGUAGES.map((code) => (
          <option key={code} value={code}>
            {labels[code]}
          </option>
        ))}
      </select>
    </label>
  );
}
