import { useTranslation } from '../../i18n/useTranslation';
import { formatDateTime } from '../../lib/format';
import type { InstitutionalProvenanceRead } from '../../types/academicRequests';

// Origem e momento dos dados: o serviço institucional, não os documentos.
export function ProvenanceNote({ provenance }: { provenance: InstitutionalProvenanceRead }) {
  const { t, language } = useTranslation();
  return (
    <p className="text-sm text-muted">
      {t('academicRequests.provenance', {
        queriedAt: formatDateTime(provenance.queried_at ?? provenance.attempted_at, language),
      })}
      {provenance.source_updated_at &&
        ` · ${t('academicRequests.sourceUpdatedAt', {
          updatedAt: formatDateTime(provenance.source_updated_at, language),
        })}`}
    </p>
  );
}
