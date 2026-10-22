import { Link, useParams } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';
import { LoadingState } from '../../components/feedback/LoadingState';
import { ErrorState } from '../../components/feedback/ErrorState';
import { formatDateTime } from '../../lib/format';
import { useAcademicRequest } from './hooks';
import { AcademicRequestsAccessGate, SimulatedNotice } from './AcademicRequestsAccessGate';
import { ProvenanceNote } from './ProvenanceNote';

function AcademicRequestDetail({
  requestId,
  simulated,
}: {
  requestId: string;
  simulated: boolean;
}) {
  const { t, language } = useTranslation();
  const requestQuery = useAcademicRequest(requestId);

  return (
    <>
      {simulated && <SimulatedNotice />}
      {requestQuery.isPending && <LoadingState />}
      {requestQuery.isError && (
        <ErrorState error={requestQuery.error} onRetry={() => requestQuery.refetch()} />
      )}
      {requestQuery.isSuccess && (
        <section className="card stack">
          <h2 style={{ margin: 0 }}>{requestQuery.data.item.request_type}</h2>
          <dl className="definition-grid">
            <dt>{t('academicRequests.requestId')}</dt>
            <dd>{requestQuery.data.item.request_id}</dd>
            <dt>{t('academicRequests.officialStatus')}</dt>
            <dd>{requestQuery.data.item.official_status}</dd>
            <dt>{t('academicRequests.updatedAt')}</dt>
            <dd>{formatDateTime(requestQuery.data.item.updated_at, language)}</dd>
            {requestQuery.data.item.next_step && (
              <>
                <dt>{t('academicRequests.nextStep')}</dt>
                <dd>{requestQuery.data.item.next_step}</dd>
              </>
            )}
          </dl>
          <p className="text-sm text-muted">{t('academicRequests.statusAsReceived')}</p>
          <ProvenanceNote provenance={requestQuery.data.provenance} />
        </section>
      )}
    </>
  );
}

export function AcademicRequestDetailPage() {
  const { t } = useTranslation();
  const { requestId } = useParams();

  return (
    <div className="content-narrow">
      <div className="page-header">
        <Link className="text-sm" to="/app/academic-requests">
          ‹ {t('academicRequests.title')}
        </Link>
      </div>
      <AcademicRequestsAccessGate>
        {(access) =>
          requestId ? (
            <AcademicRequestDetail requestId={requestId} simulated={access.simulated} />
          ) : null
        }
      </AcademicRequestsAccessGate>
    </div>
  );
}
