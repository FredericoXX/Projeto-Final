import { http, HttpResponse } from 'msw';
import {
  activeConversation,
  adminUser,
  makeVersion,
  sampleDocument,
} from './fixtures';
import type { ConversationAskResponse, MessageRead } from '../types/conversations';

export const API = 'http://localhost/api/v1';

// Valid demo credentials used by the default login handler.
export const VALID_EMAIL = 'admin@example.edu';
export const VALID_PASSWORD = 'password123';

function domainError(code: string, message: string, status: number) {
  return HttpResponse.json({ detail: { code, message } }, { status });
}

function userMessage(content: string): MessageRead {
  return {
    id: 'user-msg-1',
    conversation_id: activeConversation.id,
    institution_id: adminUser.institution_id,
    user_id: adminUser.id,
    role: 'user',
    content,
    language: 'pt',
    reply_to_message_id: null,
    extra_metadata: { turn_type: 'institutional_question' },
    created_at: '2026-02-01T09:10:00Z',
    sources: [],
  };
}

// Happy-path defaults; individual tests override with server.use(...).
export const handlers = [
  http.post(`${API}/auth/login`, async ({ request }) => {
    const body = (await request.json()) as { email: string; password: string };
    if (body.email === VALID_EMAIL && body.password === VALID_PASSWORD) {
      return HttpResponse.json({ access_token: 'test-token', token_type: 'bearer' });
    }
    return domainError('authentication_failed', 'Invalid credentials.', 401);
  }),

  http.get(`${API}/auth/me`, () => HttpResponse.json(adminUser)),

  http.get(`${API}/conversations`, () =>
    HttpResponse.json({ items: [activeConversation], total: 1, limit: 20, offset: 0 }),
  ),

  http.post(`${API}/conversations`, async ({ request }) => {
    const body = (await request.json()) as { title?: string };
    return HttpResponse.json(
      { ...activeConversation, id: 'new-conversation', title: body.title ?? null },
      { status: 201 },
    );
  }),

  http.get(`${API}/conversations/:id`, () => HttpResponse.json(activeConversation)),

  http.get(`${API}/conversations/:id/messages`, () =>
    HttpResponse.json({ items: [], total: 0, limit: 100, offset: 0 }),
  ),

  http.post(`${API}/conversations/:id/ask`, async ({ request }) => {
    const body = (await request.json()) as { query: string };
    const response: ConversationAskResponse = {
      status: 'answered',
      conversation_id: activeConversation.id,
      user_message: userMessage(body.query),
      assistant_message: {
        id: 'assistant-msg-1',
        conversation_id: activeConversation.id,
        institution_id: adminUser.institution_id,
        user_id: null,
        role: 'assistant',
        content: 'The enrollment period runs in September.',
        language: 'pt',
        reply_to_message_id: 'user-msg-1',
        extra_metadata: { answer_status: 'answered' },
        created_at: '2026-02-01T09:10:01Z',
        sources: [
          {
            id: 'src-1',
            evidence_id: 'E1',
            citation_index: 0,
            chunk_id: 'chunk-1',
            document_id: 'doc-1',
            document_version_id: 'ver-1',
            document_title: 'Academic Calendar',
            chunk_index: 2,
            source_url: 'https://example.edu/calendar',
            official_source: true,
            language: 'pt',
            valid_from: null,
            valid_until: null,
            created_at: '2026-02-01T09:10:01Z',
          },
        ],
      },
    };
    return HttpResponse.json(response, { status: 201 });
  }),

  http.get(`${API}/documents`, () =>
    HttpResponse.json({ items: [sampleDocument], total: 1, limit: 20, offset: 0 }),
  ),

  http.post(`${API}/documents`, () => HttpResponse.json(sampleDocument, { status: 201 })),

  http.get(`${API}/documents/:id`, () => HttpResponse.json(sampleDocument)),

  http.get(`${API}/documents/:id/versions`, () =>
    HttpResponse.json({ items: [makeVersion()], total: 1, limit: 50, offset: 0 }),
  ),

  http.post(`${API}/documents/:id/versions`, () =>
    HttpResponse.json(makeVersion(), { status: 201 }),
  ),

  http.post(`${API}/documents/:id/versions/:versionId/reprocess`, () =>
    HttpResponse.json(makeVersion({ processing_status: 'processed' })),
  ),
];
