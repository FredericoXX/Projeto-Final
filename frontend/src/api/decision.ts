import { apiRequest } from './client';
import type { UUID } from '../types/api';
import type {
  ConversationDecisionResponse,
  DecisionStatusRead,
  DecisionTurnRequest,
} from '../types/decision';

export function getDecisionStatus(signal?: AbortSignal): Promise<DecisionStatusRead> {
  return apiRequest<DecisionStatusRead>('/decision/status', { signal });
}

// Turno da política v1.7. Só é usado quando o utilizador escolhe o modo
// experimental; o envio normal continua a ser /ask (B0).
export function decideInConversation(
  conversationId: UUID,
  payload: DecisionTurnRequest,
  signal?: AbortSignal,
): Promise<ConversationDecisionResponse> {
  return apiRequest<ConversationDecisionResponse>(`/conversations/${conversationId}/decide`, {
    method: 'POST',
    body: payload,
    signal,
  });
}
