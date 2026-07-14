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

// Only the fields the frontend is allowed to send. institution_id, user_id,
// role, reply_to_message_id, sources, status and metadata are never sent.
export interface AnsweringRequest {
  query: string;
  language?: string;
  top_k?: number;
  official_only?: boolean;
}
