import type { MessageRead } from '../../types/conversations';
import type {
  ClarificationOption,
  DecisionAction,
  RecommendedDestination,
} from '../../types/decision';

export const DECISION_TURN_TYPE = 'policy_decision';

const ACTIONS: readonly DecisionAction[] = ['answer', 'clarify', 'abstain', 'escalate'];

export interface DecisionSnapshot {
  action: DecisionAction;
  rule: string;
  policyVersion: string;
  clarificationOptions: ClarificationOption[];
  destination: RecommendedDestination | null;
  gapItems: string[];
  temporalNotice: boolean;
}

function readString(source: Record<string, unknown>, key: string): string | null {
  const value = source[key];
  return typeof value === 'string' ? value : null;
}

function readObject(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}

/**
 * Lê os metadados públicos de um turno da política a partir da mensagem
 * persistida, como o encaminhamento E1: uma conversa reaberta mostra o que foi
 * decidido na altura. Cada campo é verificado antes de ser usado.
 */
export function readDecisionSnapshot(message: MessageRead): DecisionSnapshot | null {
  const metadata = message.extra_metadata;
  if (!metadata || metadata['turn_type'] !== DECISION_TURN_TYPE) {
    return null;
  }
  const action = readString(metadata, 'decision_outcome');
  const rule = readString(metadata, 'decision_rule');
  const policyVersion = readString(metadata, 'policy_version');
  if (!action || !ACTIONS.includes(action as DecisionAction) || !rule || !policyVersion) {
    return null;
  }
  const options = Array.isArray(metadata['clarification_options'])
    ? (metadata['clarification_options'] as unknown[]).flatMap((raw) => {
        const option = readObject(raw);
        const readingId = option && readString(option, 'reading_id');
        const label = option && readString(option, 'label');
        return readingId && label ? [{ reading_id: readingId, label }] : [];
      })
    : [];
  const rawDestination = readObject(metadata['recommended_destination']);
  const name = rawDestination && readString(rawDestination, 'name');
  const serviceId = rawDestination && readString(rawDestination, 'service_id');
  const destination =
    rawDestination && name && serviceId
      ? {
          service_id: serviceId,
          name,
          email: readString(rawDestination, 'email'),
          url: readString(rawDestination, 'url'),
        }
      : null;
  const gapItems = Array.isArray(metadata['gap_items'])
    ? (metadata['gap_items'] as unknown[]).filter((item): item is string => typeof item === 'string')
    : [];
  return {
    action: action as DecisionAction,
    rule,
    policyVersion,
    clarificationOptions: options,
    destination,
    gapItems,
    temporalNotice: metadata['temporal_notice'] === true,
  };
}
