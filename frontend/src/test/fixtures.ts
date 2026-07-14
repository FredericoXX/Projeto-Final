import type { UserRead } from '../types/auth';
import type {
  ConversationRead,
  MessageRead,
  MessageSourceRead,
} from '../types/conversations';
import type { DocumentRead, DocumentVersionRead } from '../types/documents';

export const adminUser: UserRead = {
  id: '11111111-1111-1111-1111-111111111111',
  institution_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  full_name: 'Admin Example',
  email: 'admin@example.edu',
  role: 'admin',
  is_active: true,
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-01T10:00:00Z',
};

export const regularUser: UserRead = {
  ...adminUser,
  id: '22222222-2222-2222-2222-222222222222',
  full_name: 'Staff Example',
  email: 'staff@example.edu',
  role: 'staff',
};

export const activeConversation: ConversationRead = {
  id: '33333333-3333-3333-3333-333333333333',
  institution_id: adminUser.institution_id,
  user_id: adminUser.id,
  title: 'Academic matters',
  language: 'pt',
  status: 'active',
  extra_metadata: null,
  created_at: '2026-02-01T09:00:00Z',
  updated_at: '2026-02-01T09:00:00Z',
};

export const closedConversation: ConversationRead = {
  ...activeConversation,
  id: '44444444-4444-4444-4444-444444444444',
  title: 'Closed conversation',
  status: 'closed',
};

export function makeSource(overrides: Partial<MessageSourceRead> = {}): MessageSourceRead {
  return {
    id: 'source-1',
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
    created_at: '2026-02-01T09:05:00Z',
    ...overrides,
  };
}

export function makeMessage(overrides: Partial<MessageRead> = {}): MessageRead {
  return {
    id: 'msg-1',
    conversation_id: activeConversation.id,
    institution_id: adminUser.institution_id,
    user_id: null,
    role: 'assistant',
    content: 'The enrollment period runs in September.',
    language: 'pt',
    reply_to_message_id: null,
    extra_metadata: { answer_status: 'answered' },
    created_at: '2026-02-01T09:05:00Z',
    sources: [],
    ...overrides,
  };
}

export const sampleDocument: DocumentRead = {
  id: 'doc-1',
  institution_id: adminUser.institution_id,
  created_by_user_id: adminUser.id,
  title: 'Academic Calendar',
  description: 'Official academic calendar',
  language: 'pt',
  source_url: 'https://example.edu/calendar',
  official_source: true,
  is_active: true,
  valid_from: null,
  valid_until: null,
  created_at: '2026-01-10T10:00:00Z',
  updated_at: '2026-01-10T10:00:00Z',
};

export function makeVersion(overrides: Partial<DocumentVersionRead> = {}): DocumentVersionRead {
  return {
    id: 'ver-1',
    document_id: sampleDocument.id,
    institution_id: adminUser.institution_id,
    uploaded_by_user_id: adminUser.id,
    version_number: 1,
    original_filename: 'calendar.pdf',
    mime_type: 'application/pdf',
    size_bytes: 20480,
    checksum_sha256: 'a'.repeat(64),
    processing_status: 'processed',
    processing_error: null,
    page_count: 3,
    created_at: '2026-01-10T10:05:00Z',
    updated_at: '2026-01-10T10:06:00Z',
    processed_at: '2026-01-10T10:06:00Z',
    ...overrides,
  };
}
