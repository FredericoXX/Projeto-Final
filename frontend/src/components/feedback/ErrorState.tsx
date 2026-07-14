import { useTranslation } from '../../i18n/useTranslation';
import { errorTranslationKey } from '../../api/errors';

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
}

export function ErrorState({ error, onRetry }: ErrorStateProps) {
  const { t } = useTranslation();
  return (
    <div className="state-block state-block--error" role="alert">
      <p>{t(errorTranslationKey(error))}</p>
      {onRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          {t('common.retry')}
        </button>
      )}
    </div>
  );
}
