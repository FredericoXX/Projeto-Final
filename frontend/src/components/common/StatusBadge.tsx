import { useTranslation } from '../../i18n/useTranslation';
import type { TranslationKey } from '../../i18n';

type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

const PROCESSING_TONE: Record<string, BadgeTone> = {
  pending: 'neutral',
  processing: 'info',
  processed: 'success',
  failed: 'danger',
};

const PROCESSING_LABEL: Record<string, TranslationKey> = {
  pending: 'documents.status.pending',
  processing: 'documents.status.processing',
  processed: 'documents.status.processed',
  failed: 'documents.status.failed',
};

const CONVERSATION_TONE: Record<string, BadgeTone> = {
  active: 'success',
  closed: 'neutral',
  archived: 'neutral',
};

const CONVERSATION_LABEL: Record<string, TranslationKey> = {
  active: 'conversations.status.active',
  closed: 'conversations.status.closed',
  archived: 'conversations.status.archived',
};

export function ProcessingStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const tone = PROCESSING_TONE[status] ?? 'neutral';
  const labelKey = PROCESSING_LABEL[status];
  return <span className={`badge badge--${tone}`}>{labelKey ? t(labelKey) : status}</span>;
}

export function ConversationStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const tone = CONVERSATION_TONE[status] ?? 'neutral';
  const labelKey = CONVERSATION_LABEL[status];
  return <span className={`badge badge--${tone}`}>{labelKey ? t(labelKey) : status}</span>;
}

export function OfficialBadge({ official }: { official: boolean }) {
  const { t } = useTranslation();
  return (
    <span className={`badge badge--${official ? 'info' : 'neutral'}`}>
      {official ? t('sources.official') : t('sources.unofficial')}
    </span>
  );
}
