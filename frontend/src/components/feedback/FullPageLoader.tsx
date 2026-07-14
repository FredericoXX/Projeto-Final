import { useTranslation } from '../../i18n/useTranslation';

export function FullPageLoader() {
  const { t } = useTranslation();
  return (
    <div className="login-shell" role="status" aria-live="polite">
      <p className="text-muted">{t('auth.initializing')}</p>
    </div>
  );
}
