import { apiRequest, apiRequestBlob } from './client';
import type {
  DocumentCreateRequest,
  DocumentFilters,
  DocumentListResponse,
  DocumentRead,
  DocumentVersionListResponse,
  DocumentVersionRead,
} from '../types/documents';
import type { UUID } from '../types/api';

export function listDocuments(
  params: DocumentFilters & { limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<DocumentListResponse> {
  const query = new URLSearchParams();
  query.set('limit', String(params.limit ?? 20));
  query.set('offset', String(params.offset ?? 0));
  if (params.is_active !== undefined) query.set('is_active', String(params.is_active));
  if (params.official_source !== undefined) {
    query.set('official_source', String(params.official_source));
  }
  if (params.language) query.set('language', params.language);
  return apiRequest<DocumentListResponse>(`/documents?${query.toString()}`, { signal });
}

export function createDocument(
  payload: DocumentCreateRequest,
  signal?: AbortSignal,
): Promise<DocumentRead> {
  return apiRequest<DocumentRead>('/documents', {
    method: 'POST',
    body: payload,
    signal,
  });
}

export function getDocument(documentId: UUID, signal?: AbortSignal): Promise<DocumentRead> {
  return apiRequest<DocumentRead>(`/documents/${documentId}`, { signal });
}

export function listDocumentVersions(
  documentId: UUID,
  params: { limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<DocumentVersionListResponse> {
  const query = new URLSearchParams();
  query.set('limit', String(params.limit ?? 50));
  query.set('offset', String(params.offset ?? 0));
  return apiRequest<DocumentVersionListResponse>(
    `/documents/${documentId}/versions?${query.toString()}`,
    { signal },
  );
}

export function uploadDocumentVersion(
  documentId: UUID,
  file: File,
  signal?: AbortSignal,
): Promise<DocumentVersionRead> {
  const formData = new FormData();
  formData.append('file', file);
  return apiRequest<DocumentVersionRead>(`/documents/${documentId}/versions`, {
    method: 'POST',
    body: formData,
    signal,
  });
}

export function reprocessDocumentVersion(
  documentId: UUID,
  versionId: UUID,
  signal?: AbortSignal,
): Promise<DocumentVersionRead> {
  return apiRequest<DocumentVersionRead>(
    `/documents/${documentId}/versions/${versionId}/reprocess`,
    { method: 'POST', signal },
  );
}

export function downloadDocumentVersion(
  documentId: UUID,
  versionId: UUID,
  signal?: AbortSignal,
): Promise<Blob> {
  return apiRequestBlob(`/documents/${documentId}/versions/${versionId}/download`, { signal });
}
