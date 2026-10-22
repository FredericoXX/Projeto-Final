import { useTranslation } from '../../i18n/useTranslation';
import type { MessageRead } from '../../types/conversations';
import { safeHttpUrl, safeMailtoUrl } from '../../lib/format';
import type { TranslationKey } from '../../i18n';
import type { DecisionAction } from '../../types/decision';
import { readDecisionSnapshot } from './decisionSnapshot';

const ACTION_LABELS: Record<DecisionAction, TranslationKey> = {
  answer: 'decision.action.answer',
  clarify: 'decision.action.clarify',
  abstain: 'decision.action.abstain',
  escalate: 'decision.action.escalate',
};

interface DecisionDetailsProps {
  message: MessageRead;
  // Continuação de uma clarificação: escolhe uma leitura e inicia uma nova
  // decisão no backend, que revalida a admissibilidade. Ausente quando a
  // conversa não aceita mensagens.
  onClarify?: (messageId: string, readingId: string) => void;
  clarifyPending?: boolean;
}

/**
 * Ação decidida pela política experimental e o que a acompanha: opções de
 * clarificação, destino recomendado, itens sem suporte e aviso temporal.
 * O texto da mensagem já é o registo fiel; aqui só se acrescenta a forma
 * acionável e a identificação da regra. Nada é interpretado como HTML.
 */
export function DecisionDetails({ message, onClarify, clarifyPending }: DecisionDetailsProps) {
  const { t } = useTranslation();
  const decision = readDecisionSnapshot(message);
  if (decision === null) {
    return null;
  }
  const destination = decision.destination;
  const mailto = destination ? safeMailtoUrl(destination.email) : null;
  const href = destination ? safeHttpUrl(destination.url) : null;

  return (
    <section className="decision-details" aria-label={t('decision.sectionLabel')}>
      <span className="message-note">
        {t(ACTION_LABELS[decision.action])} · {t('decision.rule')} {decision.rule} ·{' '}
        <span className="text-muted">{decision.policyVersion}</span>
      </span>

      {decision.action === 'clarify' && decision.clarificationOptions.length > 0 && (
        <div className="list-row-meta" role="group" aria-label={t('decision.clarifyOptions')}>
          {decision.clarificationOptions.map((option) => (
            <button
              key={option.reading_id}
              type="button"
              className="btn btn-secondary"
              disabled={!onClarify || clarifyPending}
              onClick={() => onClarify?.(message.id, option.reading_id)}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}

      {decision.gapItems.length > 0 && (
        <p className="message-note">
          {t('decision.gap')}: {decision.gapItems.join('; ')}
        </p>
      )}

      {destination && (
        <div className="handoff-destination">
          <span className="message-note">↪ {t('decision.recommendation')}</span>
          <div className="list-row-meta">
            <span>
              {t('handoff.service')}: {destination.name}
            </span>
            {mailto && <a href={mailto}>{t('handoff.email')}</a>}
            {href && (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {t('handoff.link')}
              </a>
            )}
          </div>
        </div>
      )}

      {decision.temporalNotice && <p className="message-note">ⓘ {t('decision.temporal')}</p>}
    </section>
  );
}
