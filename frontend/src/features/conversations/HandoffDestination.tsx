import { useTranslation } from '../../i18n/useTranslation';
import type { MessageRead } from '../../types/conversations';
import { safeHttpUrl, safeMailtoUrl } from '../../lib/format';
import { readHandoffDestination } from './handoffSnapshot';

/**
 * Ações de contacto do encaminhamento humano.
 *
 * Os contactos já aparecem em texto no corpo da mensagem (que é o registo fiel
 * do que foi apresentado ao utilizador); aqui só se acrescenta a forma
 * acionável. Nada vindo do backend é interpretado como HTML: o React escapa o
 * nome, e o email e o URL passam pelos mesmos validadores usados nas fontes
 * documentais — um `javascript:` nunca chega a ser um link.
 */
export function HandoffDestinationActions({ message }: { message: MessageRead }) {
  const { t } = useTranslation();
  const destination = readHandoffDestination(message);
  if (destination === null) {
    return null;
  }

  const mailto = safeMailtoUrl(destination.email);
  const href = safeHttpUrl(destination.url);

  return (
    <section className="handoff-destination">
      <span className="message-note">↪ {t('handoff.note')}</span>
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
    </section>
  );
}
