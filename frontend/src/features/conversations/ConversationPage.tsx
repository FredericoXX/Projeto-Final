import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useTranslation } from '../../i18n/useTranslation';
import { useAsk, useConversation, useMessages } from './hooks';
import { MessageItem } from './MessageItem';
import { Composer } from './Composer';
import { LoadingState } from '../../components/feedback/LoadingState';
import { ErrorState } from '../../components/feedback/ErrorState';
import { EmptyState } from '../../components/feedback/EmptyState';
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
  const [askError, setAskError] = useState<string | null>(null);
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

  return (
    <div className="conversation-view">
      <div className="page-header">
        <div>
          <Link className="text-sm" to="/app/conversations">
            ‹ {t('conversations.title')}
          </Link>
          <h1>{conversation?.title ?? t('conversations.untitled')}</h1>
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
