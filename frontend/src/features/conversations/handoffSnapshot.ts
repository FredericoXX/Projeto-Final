import type { HumanHandoffDestination, MessageRead } from '../../types/conversations';

export const HANDOFF_TURN_TYPE = 'human_handoff';

function readString(source: Record<string, unknown>, key: string): string | null {
  const value = source[key];
  return typeof value === 'string' ? value : null;
}

/**
 * Lê o destino do snapshot persistido na mensagem.
 *
 * A fonte é sempre `extra_metadata`, nunca estado React: é isso que faz o
 * encaminhamento continuar visível quando a conversa é reaberta mais tarde, e
 * é isso que garante que uma mensagem histórica mostra o destino apresentado
 * na altura — não o que a instituição tem configurado hoje.
 *
 * O metadata é `Record<string, unknown>`: cada campo é verificado antes de ser
 * usado, em vez de assumir a forma que o backend devolve hoje.
 */
export function readHandoffDestination(message: MessageRead): HumanHandoffDestination | null {
  const metadata = message.extra_metadata;
  if (!metadata || metadata['turn_type'] !== HANDOFF_TURN_TYPE) {
    return null;
  }
  const raw = metadata['handoff_destination'];
  if (typeof raw !== 'object' || raw === null) {
    return null;
  }
  const destination = raw as Record<string, unknown>;
  const name = readString(destination, 'name');
  if (name === null) {
    return null;
  }
  return {
    name,
    email: readString(destination, 'email'),
    url: readString(destination, 'url'),
  };
}
