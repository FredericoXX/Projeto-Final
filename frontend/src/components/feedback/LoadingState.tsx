import { useTranslation } from '../../i18n/useTranslation';

export function LoadingState({ label }: { label?: string }) {
  const { t } = useTranslation();
  return (
    <div className="state-block" role="status" aria-live="polite">
      {label ?? t('common.loading')}
    </div>
  );
}
