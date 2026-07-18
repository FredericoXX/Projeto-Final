import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';
import { useAsk, useConversation, useMessages, useRenameConversation } from './hooks';
import { MessageItem } from './MessageItem';
import { Composer } from './Composer';
import { LoadingState } from '../../components/feedback/LoadingState';
import { ErrorState } from '../../components/feedback/ErrorState';
import { EmptyState } from '../../components/feedback/EmptyState';
import { InlineError } from '../../components/feedback/InlineError';
import { ConversationStatusBadge } from '../../components/common/StatusBadge';
import { errorTranslationKey } from '../../api/errors';
import type { MessageRead } from '../../types/conversations';

function sortMessages(messages: MessageRead[]): MessageRead[] {
  const unique = [...new Map(messages.map((message) => [message.id, message])).values()];
  return unique.sort((a, b) => {
    if (a.created_at === b.created_at) {
      return a.id < b.id ? -1 : 1;
    }
    return a.created_at < b.created_at ? -1 : 1;
  });
}

export function ConversationPage() {
  const { conversationId = '' } = useParams();
  const { t } = useTranslation();
  const conversationQuery = useConversation(conversationId);
  const messagesQuery = useMessages(conversationId);
  const ask = useAsk(conversationId);
  const rename = useRenameConversation(conversationId);
  const [askError, setAskError] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState('');
  const [renameError, setRenameError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const preserveScrollRef = useRef<{ height: number; top: number } | null>(null);

  const messages = useMemo(
    () => sortMessages(messagesQuery.data?.pages.flatMap((page) => page.items) ?? []),
    [messagesQuery.data],
  );

  useEffect(() => {
    const node = scrollRef.current;
    if (node) {
      const previous = preserveScrollRef.current;
      if (previous) {
        node.scrollTop = previous.top + node.scrollHeight - previous.height;
        preserveScrollRef.current = null;
      } else {
        node.scrollTop = node.scrollHeight;
      }
    }
  }, [messages.length]);

  async function handleLoadOlder() {
    const node = scrollRef.current;
    if (node) {
      preserveScrollRef.current = { height: node.scrollHeight, top: node.scrollTop };
    }
    try {
      await messagesQuery.fetchPreviousPage();
    } catch {
      preserveScrollRef.current = null;
    }
  }

  async function handleAsk(query: string, officialOnly: boolean): Promise<boolean> {
    setAskError(null);
    try {
      await ask.mutateAsync({ query, official_only: officialOnly });
      return true;
    } catch (error) {
      // 502/503 (and any error) never inject a local message — the backend
      // does not persist partial turns. Keep the typed text for retry.
      setAskError(t(errorTranslationKey(error)));
      return false;
    }
  }

  if (conversationQuery.isError) {
    return (
      <div className="content-narrow">
        <ErrorState error={conversationQuery.error} />
        <Link className="btn btn-secondary" to="/app/conversations">
          {t('common.back')}
        </Link>
      </div>
    );
  }

  const conversation = conversationQuery.data;
  const isActive = conversation?.status === 'active';

  async function handleRenameSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = renameValue.trim();
    if (!trimmed || rename.isPending) {
      return;
    }
    setRenameError(null);
    try {
      await rename.mutateAsync(trimmed);
      setRenaming(false);
    } catch (error) {
      // O erro mantém o modo de edição para nova tentativa.
      setRenameError(t(errorTranslationKey(error)));
    }
  }

  function startRenaming() {
    setRenameValue(conversation?.title ?? '');
    setRenameError(null);
    setRenaming(true);
  }

  function cancelRenaming() {
    setRenaming(false);
    setRenameError(null);
  }

  return (
    <div className="conversation-view">
      <div className="page-header">
        <div style={{ minWidth: 0, flex: 1 }}>
          <Link className="text-sm" to="/app/conversations">
            ‹ {t('conversations.title')}
          </Link>
          {renaming ? (
            <form className="composer-row" onSubmit={handleRenameSubmit}>
              <label className="visually-hidden" htmlFor="rename-conversation">
                {t('conversations.renameLabel')}
              </label>
              <input
                id="rename-conversation"
                className="input"
                value={renameValue}
                maxLength={255}
                required
                autoFocus
                onChange={(event) => setRenameValue(event.target.value)}
              />
              <button
                type="submit"
                className="btn btn-primary"
                disabled={rename.isPending || renameValue.trim().length === 0}
              >
                {rename.isPending ? t('form.saving') : t('form.save')}
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={rename.isPending}
                onClick={cancelRenaming}
              >
                {t('common.cancel')}
              </button>
            </form>
          ) : (
            <div className="composer-row" style={{ alignItems: 'center' }}>
              <h1 style={{ margin: 0, overflowWrap: 'anywhere' }}>
                {conversation?.title ?? t('conversations.untitled')}
              </h1>
              {conversation && (
                <button type="button" className="btn btn-ghost" onClick={startRenaming}>
                  {t('conversations.rename')}
                </button>
              )}
            </div>
          )}
          {renameError && <InlineError message={renameError} />}
        </div>
        {conversation && <ConversationStatusBadge status={conversation.status} />}
      </div>

      <div className="messages-scroll" ref={scrollRef}>
        {messagesQuery.isPending && <LoadingState />}
        {messagesQuery.isError && (
          <ErrorState error={messagesQuery.error} onRetry={() => messagesQuery.refetch()} />
        )}
        {messagesQuery.isSuccess && messages.length === 0 && (
          <EmptyState message={t('conversations.noMessages')} />
        )}
        {messagesQuery.hasPreviousPage && (
          <button
            type="button"
            className="btn btn-ghost load-older"
            disabled={messagesQuery.isFetchingPreviousPage}
            onClick={handleLoadOlder}
          >
            {messagesQuery.isFetchingPreviousPage
              ? t('common.loading')
              : t('conversations.loadOlder')}
          </button>
        )}
        {messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
      </div>

      {askError && (
        <p className="inline-error" role="alert" aria-live="assertive">
          {askError}
        </p>
      )}

      {conversation && !isActive && (
        <p className="message-note" role="status" style={{ padding: '0.75rem 0' }}>
          {conversation.status === 'archived'
            ? t('conversations.archivedNotice')
            : t('conversations.closedNotice')}
        </p>
      )}

      {conversation && isActive && (
        <Composer disabled={!isActive} pending={ask.isPending} onSubmit={handleAsk} />
      )}
    </div>
  );
}
