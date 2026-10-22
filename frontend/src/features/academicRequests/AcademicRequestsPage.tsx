import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';
import { LoadingState } from '../../components/feedback/LoadingState';
import { ErrorState } from '../../components/feedback/ErrorState';
import { EmptyState } from '../../components/feedback/EmptyState';
import { formatDateTime } from '../../lib/format';
import { useAcademicRequests } from './hooks';
import { AcademicRequestsAccessGate, SimulatedNotice } from './AcademicRequestsAccessGate';
import { ProvenanceNote } from './ProvenanceNote';

function AcademicRequestsList({ simulated }: { simulated: boolean }) {
  const { t, language } = useTranslation();
  const navigate = useNavigate();
  const requestsQuery = useAcademicRequests();

  return (
    <>
      {simulated && <SimulatedNotice />}
      {requestsQuery.isPending && <LoadingState />}
      {requestsQuery.isError && (
        <ErrorState error={requestsQuery.error} onRetry={() => requestsQuery.refetch()} />
      )}
      {requestsQuery.isSuccess && (
        <>
          {requestsQuery.data.items.length === 0 ? (
            <EmptyState message={t('academicRequests.empty')} />
          ) : (
            <div className="list">
              {requestsQuery.data.items.map((request) => (
                <button
                  key={request.request_id}
                  type="button"
                  className="list-row"
                  onClick={() =>
                    navigate(`/app/academic-requests/${encodeURIComponent(request.request_id)}`)
                  }
                >
                  <span className="list-row-main">
                    <span className="list-row-title">{request.request_type}</span>
                    <span className="list-row-meta">
                      <span>{t('academicRequests.officialStatus')}:</span>
                      <span className="badge badge--neutral">{request.official_status}</span>
                      <span>{request.request_id}</span>
                    </span>
                  </span>
                  <span className="text-sm text-muted">
                    {t('academicRequests.updatedAt')}{' '}
                    {formatDateTime(request.updated_at, language)}
                  </span>
                </button>
              ))}
            </div>
          )}
          <ProvenanceNote provenance={requestsQuery.data.provenance} />
        </>
      )}
    </>
  );
}

export function AcademicRequestsPage() {
  const { t } = useTranslation();
  return (
    <div className="content-narrow">
      <div className="page-header">
        <h1>{t('academicRequests.title')}</h1>
      </div>
      <p className="text-sm text-muted">{t('academicRequests.intro')}</p>
      <AcademicRequestsAccessGate>
        {(access) => <AcademicRequestsList simulated={access.simulated} />}
      </AcademicRequestsAccessGate>
    </div>
  );
}
