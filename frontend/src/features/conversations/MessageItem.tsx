import { useTranslation } from '../../i18n/useTranslation';
import type { MessageRead } from '../../types/conversations';
import { SourceList } from './SourceList';
import { HandoffDestinationActions } from './HandoffDestination';
import { DecisionDetails } from './DecisionDetails';
import { readDecisionSnapshot } from './decisionSnapshot';

function isInsufficient(message: MessageRead): boolean {
  const status = message.extra_metadata?.['answer_status'];
  return status === 'insufficient_evidence';
}

interface MessageItemProps {
  message: MessageRead;
  onClarify?: (messageId: string, readingId: string) => void;
  clarifyPending?: boolean;
}

export function MessageItem({ message, onClarify, clarifyPending }: MessageItemProps) {
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
  const decision = isAssistant ? readDecisionSnapshot(message) : null;
  // Num turno da política, só ANSWER é uma resposta fundamentada: as fontes de
  // um encaminhamento citam orientações divergentes ou excertos de procedimento.
  const grounded =
    isAssistant && message.sources.length > 0 && (decision === null || decision.action === 'answer');

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
      {decision && (
        <DecisionDetails message={message} onClarify={onClarify} clarifyPending={clarifyPending} />
      )}
      {isAssistant && <SourceList sources={message.sources} />}
    </article>
  );
}
