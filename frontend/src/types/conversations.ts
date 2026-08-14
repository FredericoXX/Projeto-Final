import type { IsoDate, IsoDateTime, PaginatedResponse, UUID } from './api';

export type ConversationStatus = 'active' | 'closed' | 'archived';

export interface ConversationRead {
  id: UUID;
  institution_id: UUID;
  user_id: UUID;
  title: string | null;
  language: string | null;
  status: ConversationStatus;
  extra_metadata: Record<string, unknown> | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export type ConversationListResponse = PaginatedResponse<ConversationRead>;

export interface ConversationCreateRequest {
  title?: string;
  language?: string;
}

export interface MessageSourceRead {
  id: UUID;
  evidence_id: string;
  citation_index: number;
  chunk_id: UUID;
  document_id: UUID;
  document_version_id: UUID;
  document_title: string;
  chunk_index: number;
  source_url: string | null;
  official_source: boolean;
  language: string;
  valid_from: IsoDate | null;
  valid_until: IsoDate | null;
  created_at: IsoDateTime;
}

export type MessageRole = 'user' | 'assistant' | 'system';

export interface MessageRead {
  id: UUID;
  conversation_id: UUID;
  institution_id: UUID;
  user_id: UUID | null;
  role: MessageRole;
  content: string;
  language: string | null;
  reply_to_message_id: UUID | null;
  extra_metadata: Record<string, unknown> | null;
  created_at: IsoDateTime;
  sources: MessageSourceRead[];
}

export type MessageListResponse = PaginatedResponse<MessageRead>;

export type AnswerStatus = 'answered' | 'insufficient_evidence';

export interface ConversationAskResponse {
  status: AnswerStatus;
  conversation_id: UUID;
  user_message: MessageRead;
  assistant_message: MessageRead;
}

// Encaminhamento humano E1. O desfecho é sempre 'escalate' — o cliente não o
// escolhe, tal como não escolhe o destino nem a origem do encaminhamento.
export interface HumanHandoffDestination {
  name: string;
  email: string | null;
  url: string | null;
}

export interface ConversationHandoffResponse {
  outcome: 'escalate';
  conversation_id: UUID;
  destination: HumanHandoffDestination;
  assistant_message: MessageRead;
}

// Apenas os campos que o frontend pode enviar. institution_id, user_id, role,
// reply_to_message_id, sources, status e metadata nunca são enviados.
export interface AnsweringRequest {
  query: string;
  language?: string;
  top_k?: number;
  official_only?: boolean;
}
