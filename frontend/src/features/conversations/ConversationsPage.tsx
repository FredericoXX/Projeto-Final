import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';
import { useConversations, useCreateConversation } from './hooks';
import { LoadingState } from '../../components/feedback/LoadingState';
import { ErrorState } from '../../components/feedback/ErrorState';
import { EmptyState } from '../../components/feedback/EmptyState';
import { InlineError } from '../../components/feedback/InlineError';
import { Pagination } from '../../components/common/Pagination';
import { ConversationStatusBadge } from '../../components/common/StatusBadge';
import { errorTranslationKey } from '../../api/errors';
import { formatDateTime } from '../../lib/format';

const PAGE_SIZE = 20;

export function ConversationsPage() {
  const { t, language } = useTranslation();
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const [createError, setCreateError] = useState<string | null>(null);

  const conversationsQuery = useConversations(offset);
  const createMutation = useCreateConversation();

  // Sem formulário de título: a conversa é criada com payload vazio e o
  // título automático chega com a primeira pergunta persistida. O título
  // nunca é gerado no frontend.
  async function handleCreate() {
    if (createMutation.isPending) {
      return;
    }
    setCreateError(null);
    try {
      const conversation = await createMutation.mutateAsync({});
      navigate(`/app/conversations/${conversation.id}`);
    } catch (error) {
      setCreateError(t(errorTranslationKey(error)));
    }
  }

  return (
    <div className="content-narrow">
      <div className="page-header">
        <h1>{t('conversations.title')}</h1>
        <button
          type="button"
          className="btn btn-primary"
          disabled={createMutation.isPending}
          onClick={handleCreate}
        >
          {createMutation.isPending ? t('conversations.creating') : t('conversations.new')}
        </button>
      </div>

      {createError && <InlineError message={createError} />}

      {conversationsQuery.isPending && <LoadingState />}
      {conversationsQuery.isError && (
        <ErrorState error={conversationsQuery.error} onRetry={() => conversationsQuery.refetch()} />
      )}
      {conversationsQuery.isSuccess &&
        (conversationsQuery.data.items.length === 0 ? (
          <EmptyState message={t('conversations.empty')} />
        ) : (
          <>
            <div className="list">
              {conversationsQuery.data.items.map((conversation) => (
                <button
                  key={conversation.id}
                  type="button"
                  className="list-row"
                  onClick={() => navigate(`/app/conversations/${conversation.id}`)}
                >
                  <span className="list-row-main">
                    <span className="list-row-title">
                      {conversation.title ?? t('conversations.untitled')}
                    </span>
                    <span className="list-row-meta">
                      <ConversationStatusBadge status={conversation.status} />
                      {conversation.language && <span>{conversation.language}</span>}
                      <span>
                        {t('conversations.updatedAt')}:{' '}
                        {formatDateTime(conversation.updated_at, language)}
                      </span>
                    </span>
                  </span>
                  <span aria-hidden="true">›</span>
                </button>
              ))}
            </div>
            <Pagination
              offset={offset}
              limit={PAGE_SIZE}
              total={conversationsQuery.data.total}
              onChange={setOffset}
            />
          </>
        ))}
    </div>
  );
}
