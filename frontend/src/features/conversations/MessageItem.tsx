import { useTranslation } from '../../i18n/useTranslation';
import type { MessageRead } from '../../types/conversations';
import { SourceList } from './SourceList';

function isInsufficient(message: MessageRead): boolean {
  const status = message.extra_metadata?.['answer_status'];
  return status === 'insufficient_evidence';
}

export function MessageItem({ message }: { message: MessageRead }) {
  const { t } = useTranslation();
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const roleClass = isUser ? 'user' : isAssistant ? 'assistant' : 'system';
  const roleLabel = isUser
    ? t('message.you')
    : isAssistant
      ? t('message.assistant')
      : t('message.system');
  const insufficient = isAssistant && isInsufficient(message);
  const grounded = isAssistant && message.sources.length > 0;

  return (
    <article className={`message message--${roleClass}`}>
      <span className="message-role">{roleLabel}</span>
      {/* Rendered as plain text: React escapes it and CSS preserves newlines.
          Message content is untrusted and never interpreted as HTML. */}
      <div className="message-body">{message.content}</div>

      {grounded && <span className="message-note">✓ {t('message.grounded')}</span>}
      {insufficient && <span className="message-note">ⓘ {t('message.insufficient')}</span>}
      {isAssistant && <SourceList sources={message.sources} />}
    </article>
  );
}
