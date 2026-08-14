import { useTranslation } from '../../i18n/useTranslation';
import type { MessageRead } from '../../types/conversations';
import { SourceList } from './SourceList';
import { HandoffDestinationActions } from './HandoffDestination';

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
      {/* Apresentado como texto simples: o React escapa-o e o CSS preserva as
          quebras de linha. O conteúdo da mensagem não é fiável e nunca é
          interpretado como HTML. */}
      <div className="message-body">{message.content}</div>

      {grounded && <span className="message-note">✓ {t('message.grounded')}</span>}
      {insufficient && <span className="message-note">ⓘ {t('message.insufficient')}</span>}
      {isAssistant && <HandoffDestinationActions message={message} />}
      {isAssistant && <SourceList sources={message.sources} />}
    </article>
  );
}
