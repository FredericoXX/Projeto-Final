import type { UUID } from './api';
import type { MessageRead } from './conversations';

// Modo experimental da política de decisão v1.7. Contratos próprios: o /ask do
// B0 continua a devolver apenas answered / insufficient_evidence.

export type DecisionAction = 'answer' | 'clarify' | 'abstain' | 'escalate';

export interface DecisionStatusRead {
  enabled: boolean;
  policy_version: string;
  catalog_configured: boolean;
}

export interface ClarificationOption {
  reading_id: string;
  label: string;
}

export interface RecommendedDestination {
  service_id: string;
  name: string;
  email: string | null;
  url: string | null;
}

// Exatamente um de query ou clarification. institution_id, user_id e o papel
// nunca são enviados: vêm da identidade autenticada no backend.
export type DecisionTurnRequest =
  | { query: string; official_only?: boolean; language?: string }
  | {
      clarification: { message_id: UUID; reading_id: string };
      official_only?: boolean;
      language?: string;
    };

export interface ConversationDecisionResponse {
  action: DecisionAction;
  rule: string;
  policy_version: string;
  message_version: string;
  conversation_id: UUID;
  user_message: MessageRead;
  assistant_message: MessageRead;
  clarification_options: ClarificationOption[];
  destination: RecommendedDestination | null;
  gap_items: string[];
  temporal_notice: boolean;
}
