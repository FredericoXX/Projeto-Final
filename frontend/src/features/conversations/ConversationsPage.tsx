import { useState, type FormEvent } from 'react';
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
  const [creating, setCreating] = useState(false);
  const [title, setTitle] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const conversationsQuery = useConversations(offset);
  const createMutation = useCreateConversation();

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    const trimmed = title.trim();
    try {
      const conversation = await createMutation.mutateAsync(
        trimmed ? { title: trimmed } : {},
      );
      setTitle('');
      setCreating(false);
      navigate(`/app/conversations/${conversation.id}`);
    } catch (error) {
      setFormError(t(errorTranslationKey(error)));
    }
  }

  return (
    <div className="content-narrow">
      <div className="page-header">
        <h1>{t('conversations.title')}</h1>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => setCreating((open) => !open)}
        >
          {t('conversations.new')}
        </button>
      </div>

      {creating && (
        <form className="card stack" onSubmit={handleCreate} style={{ marginBottom: '1.5rem' }}>
          <div className="field">
            <label className="field-label" htmlFor="new-conversation-title">
              {t('conversations.titleField')}
            </label>
            <input
              id="new-conversation-title"
              className="input"
              value={title}
              maxLength={255}
              placeholder={t('conversations.titlePlaceholder')}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          {formError && <InlineError message={formError} />}
          <div className="composer-row">
            <button type="submit" className="btn btn-primary" disabled={createMutation.isPending}>
              {t('conversations.create')}
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setCreating(false);
                setFormError(null);
              }}
            >
              {t('common.cancel')}
            </button>
          </div>
        </form>
      )}

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
