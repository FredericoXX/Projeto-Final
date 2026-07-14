import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createDocument,
  getDocument,
  listDocuments,
  listDocumentVersions,
  reprocessDocumentVersion,
  uploadDocumentVersion,
} from '../../api/documents';
import type {
  DocumentCreateRequest,
  DocumentFilters,
  DocumentListResponse,
  DocumentRead,
  DocumentVersionListResponse,
  DocumentVersionRead,
} from '../../types/documents';
import type { UUID } from '../../types/api';

export const documentKeys = {
  list: (filters: DocumentFilters, offset: number) =>
    ['documents', { filters, offset }] as const,
  detail: (id: UUID) => ['document', id] as const,
  versions: (id: UUID) => ['documentVersions', id] as const,
};

export function useDocuments(filters: DocumentFilters, offset: number) {
  return useQuery<DocumentListResponse>({
    queryKey: documentKeys.list(filters, offset),
    queryFn: ({ signal }) => listDocuments({ ...filters, offset }, signal),
  });
}

export function useCreateDocument() {
  const queryClient = useQueryClient();
  return useMutation<DocumentRead, unknown, DocumentCreateRequest>({
    mutationFn: (payload) => createDocument(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });
}

export function useDocument(documentId: UUID) {
  return useQuery<DocumentRead>({
    queryKey: documentKeys.detail(documentId),
    queryFn: ({ signal }) => getDocument(documentId, signal),
  });
}

export function useDocumentVersions(documentId: UUID) {
  return useQuery<DocumentVersionListResponse>({
    queryKey: documentKeys.versions(documentId),
    queryFn: ({ signal }) => listDocumentVersions(documentId, { limit: 50 }, signal),
  });
}

export function useUploadVersion(documentId: UUID) {
  const queryClient = useQueryClient();
  return useMutation<DocumentVersionRead, unknown, File>({
    mutationFn: (file) => uploadDocumentVersion(documentId, file),
    onSuccess: () => {
      // Processing is synchronous today: refresh the version list afterwards.
      void queryClient.invalidateQueries({ queryKey: documentKeys.versions(documentId) });
    },
  });
}

export function useReprocessVersion(documentId: UUID) {
  const queryClient = useQueryClient();
  return useMutation<DocumentVersionRead, unknown, UUID>({
    mutationFn: (versionId) => reprocessDocumentVersion(documentId, versionId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: documentKeys.versions(documentId) });
    },
  });
}
