import type { IsoDate, IsoDateTime, PaginatedResponse, UUID } from './api';

export interface DocumentRead {
  id: UUID;
  institution_id: UUID;
  created_by_user_id: UUID;
  title: string;
  description: string | null;
  language: string;
  source_url: string | null;
  official_source: boolean;
  is_active: boolean;
  valid_from: IsoDate | null;
  valid_until: IsoDate | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export type DocumentListResponse = PaginatedResponse<DocumentRead>;

// Campos editáveis via PATCH; institution_id, created_by_user_id, versões
// e campos internos nunca são enviados.
export interface DocumentUpdateRequest {
  title?: string;
  description?: string | null;
  language?: string;
  source_url?: string | null;
  official_source?: boolean;
  is_active?: boolean;
  valid_from?: IsoDate | null;
  valid_until?: IsoDate | null;
}

export interface DocumentCreateRequest {
  title: string;
  description?: string | null;
  language?: string | null;
  source_url?: string | null;
  official_source?: boolean;
  valid_from?: IsoDate | null;
  valid_until?: IsoDate | null;
}

export type ProcessingStatus = 'pending' | 'processing' | 'processed' | 'failed';

export interface DocumentVersionRead {
  id: UUID;
  document_id: UUID;
  institution_id: UUID;
  uploaded_by_user_id: UUID;
  version_number: number;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  checksum_sha256: string;
  processing_status: ProcessingStatus;
  processing_error: string | null;
  page_count: number | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  processed_at: IsoDateTime | null;
}

export type DocumentVersionListResponse = PaginatedResponse<DocumentVersionRead>;

export interface DocumentContentRead {
  text: string;
  total_characters: number;
  offset: number;
  limit: number;
}

export interface DocumentFilters {
  is_active?: boolean;
  official_source?: boolean;
  language?: string;
}
