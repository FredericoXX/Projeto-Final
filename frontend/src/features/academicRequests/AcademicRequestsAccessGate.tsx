import type { ReactNode } from 'react';
import { useTranslation } from '../../i18n/useTranslation';
import { LoadingState } from '../../components/feedback/LoadingState';
import { ErrorState } from '../../components/feedback/ErrorState';
import type { TranslationKey } from '../../i18n';
import type { AcademicRequestAccessRead } from '../../types/academicRequests';
import { useAcademicRequestsAccess } from './hooks';

const UNAVAILABLE_REASON: Record<
  Exclude<AcademicRequestAccessRead['reason'], 'available'>,
  TranslationKey
> = {
  not_permitted: 'common.accessDenied',
  not_configured: 'academicRequests.notConfigured',
  not_linked: 'academicRequests.notLinked',
};

// Mostra o conteúdo apenas a contas com associação autorizada e integração
// ativa. O backend volta a verificar tudo em cada pedido.
export function AcademicRequestsAccessGate({
  children,
}: {
  children: (access: AcademicRequestAccessRead) => ReactNode;
}) {
  const { t } = useTranslation();
  const accessQuery = useAcademicRequestsAccess();

  if (accessQuery.isPending) {
    return <LoadingState />;
  }
  if (accessQuery.isError) {
    return <ErrorState error={accessQuery.error} onRetry={() => accessQuery.refetch()} />;
  }
  const access = accessQuery.data;
  if (access.reason !== 'available') {
    return (
      <div className="state-block" role="status">
        {t(UNAVAILABLE_REASON[access.reason])}
      </div>
    );
  }
  return <>{children(access)}</>;
}

// Identificação explícita da demonstração: dados sintéticos nunca aparecem como
// se fossem institucionais.
export function SimulatedNotice() {
  const { t } = useTranslation();
  return (
    <p className="card text-sm" role="note">
      <span className="badge badge--warning">{t('academicRequests.simulatedBadge')}</span>{' '}
      {t('academicRequests.simulatedNotice')}
    </p>
  );
}
