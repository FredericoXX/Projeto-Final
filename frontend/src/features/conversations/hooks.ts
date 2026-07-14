import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from '@tanstack/react-query';
import {
  askInConversation,
  createConversation,
  getConversation,
  listConversations,
  listMessages,
} from '../../api/conversations';
import type {
  AnsweringRequest,
  ConversationAskResponse,
  ConversationCreateRequest,
  ConversationListResponse,
  ConversationRead,
  MessageListResponse,
} from '../../types/conversations';
import type { UUID } from '../../types/api';

export const conversationKeys = {
  list: (offset: number) => ['conversations', { offset }] as const,
  detail: (id: UUID) => ['conversation', id] as const,
  messages: (id: UUID) => ['messages', id] as const,
};

const MESSAGE_PAGE_SIZE = 100;

interface MessagePageParam {
  offset: number;
  limit: number;
}

type MessagePages = InfiniteData<MessageListResponse, MessagePageParam | null>;

async function listLatestMessages(
  conversationId: UUID,
  signal?: AbortSignal,
): Promise<MessageListResponse> {
  const firstPage = await listMessages(
    conversationId,
    { limit: MESSAGE_PAGE_SIZE, offset: 0 },
    signal,
  );
  if (firstPage.total <= MESSAGE_PAGE_SIZE) {
    return firstPage;
  }
  return listMessages(
    conversationId,
    { limit: MESSAGE_PAGE_SIZE, offset: firstPage.total - MESSAGE_PAGE_SIZE },
    signal,
  );
}

export function useConversations(offset: number) {
  return useQuery<ConversationListResponse>({
    queryKey: conversationKeys.list(offset),
    queryFn: ({ signal }) => listConversations({ offset }, signal),
  });
}

export function useConversation(conversationId: UUID) {
  return useQuery<ConversationRead>({
    queryKey: conversationKeys.detail(conversationId),
    queryFn: ({ signal }) => getConversation(conversationId, signal),
  });
}

export function useMessages(conversationId: UUID) {
  return useInfiniteQuery<
    MessageListResponse,
    Error,
    MessagePages,
    ReturnType<typeof conversationKeys.messages>,
    MessagePageParam | null
  >({
    queryKey: conversationKeys.messages(conversationId),
    initialPageParam: null,
    queryFn: ({ signal, pageParam }) =>
      pageParam === null
        ? listLatestMessages(conversationId, signal)
        : listMessages(conversationId, pageParam, signal),
    getNextPageParam: () => undefined,
    getPreviousPageParam: (firstPage) => {
      if (firstPage.offset <= 0) return undefined;
      const limit = Math.min(MESSAGE_PAGE_SIZE, firstPage.offset);
      return { offset: firstPage.offset - limit, limit };
    },
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation<ConversationRead, unknown, ConversationCreateRequest>({
    mutationFn: (payload) => createConversation(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
  });
}

export function useAsk(conversationId: UUID) {
  const queryClient = useQueryClient();
  return useMutation<ConversationAskResponse, unknown, AnsweringRequest>({
    mutationFn: (payload) => askInConversation(conversationId, payload),
    onSuccess: (response) => {
      // The persisted turn is the source of truth: append both returned
      // messages, de-duplicating by id, instead of an optimistic insert.
      queryClient.setQueryData<MessagePages>(
        conversationKeys.messages(conversationId),
        (current) => {
          if (!current || current.pages.length === 0) return current;
          const existing = current.pages.flatMap((page) => page.items);
          const known = new Set(existing.map((message) => message.id));
          const appended = [response.user_message, response.assistant_message].filter(
            (message) => !known.has(message.id),
          );
          if (appended.length === 0) return current;
          const lastPageIndex = current.pages.length - 1;
          const total = current.pages[lastPageIndex].total + appended.length;
          return {
            ...current,
            pages: current.pages.map((page, index) => ({
              ...page,
              total,
              items: index === lastPageIndex ? [...page.items, ...appended] : page.items,
            })),
          };
        },
      );
      void queryClient.invalidateQueries({ queryKey: ['conversations'] });
    },
  });
}
