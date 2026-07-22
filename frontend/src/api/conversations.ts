import { apiRequest } from './client';
import type {
  AnsweringRequest,
  ConversationAskResponse,
  ConversationCreateRequest,
  ConversationListResponse,
  ConversationRead,
  MessageListResponse,
} from '../types/conversations';
import type { UUID } from '../types/api';

export function listConversations(
  params: { limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<ConversationListResponse> {
  const query = new URLSearchParams();
  query.set('limit', String(params.limit ?? 20));
  query.set('offset', String(params.offset ?? 0));
  return apiRequest<ConversationListResponse>(`/conversations?${query.toString()}`, { signal });
}

export function createConversation(
  payload: ConversationCreateRequest,
  signal?: AbortSignal,
): Promise<ConversationRead> {
  return apiRequest<ConversationRead>('/conversations', {
    method: 'POST',
    body: payload,
    signal,
  });
}

export function getConversation(
  conversationId: UUID,
  signal?: AbortSignal,
): Promise<ConversationRead> {
  return apiRequest<ConversationRead>(`/conversations/${conversationId}`, { signal });
}

// Renomeação: envia apenas o título — o status nunca é tocado pela UI
// (conversas closed/archived aceitam renomear sem reabrir).
export function updateConversation(
  conversationId: UUID,
  payload: { title: string },
  signal?: AbortSignal,
): Promise<ConversationRead> {
  return apiRequest<ConversationRead>(`/conversations/${conversationId}`, {
    method: 'PATCH',
    body: payload,
    signal,
  });
}

export function listMessages(
  conversationId: UUID,
  params: { limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<MessageListResponse> {
  const query = new URLSearchParams();
  query.set('limit', String(params.limit ?? 100));
  query.set('offset', String(params.offset ?? 0));
  return apiRequest<MessageListResponse>(
    `/conversations/${conversationId}/messages?${query.toString()}`,
    { signal },
  );
}

// Única forma de a interface fazer perguntas ao assistente. A criação manual
// de mensagens (POST .../messages) nunca é usada para perguntas.
export function askInConversation(
  conversationId: UUID,
  payload: AnsweringRequest,
  signal?: AbortSignal,
): Promise<ConversationAskResponse> {
  return apiRequest<ConversationAskResponse>(`/conversations/${conversationId}/ask`, {
    method: 'POST',
    body: payload,
    signal,
  });
}
