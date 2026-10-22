import { apiRequest } from './client';
import type {
  AcademicRequestAccessRead,
  AcademicRequestDetailResponse,
  AcademicRequestListResponse,
} from '../types/academicRequests';

// Consultas iniciadas pelo utilizador: sem polling nem refetch periódico.
export function getAcademicRequestsAccess(
  signal?: AbortSignal,
): Promise<AcademicRequestAccessRead> {
  return apiRequest<AcademicRequestAccessRead>('/academic-requests/access', { signal });
}

export function listAcademicRequests(signal?: AbortSignal): Promise<AcademicRequestListResponse> {
  return apiRequest<AcademicRequestListResponse>('/academic-requests', { signal });
}

export function getAcademicRequest(
  requestId: string,
  signal?: AbortSignal,
): Promise<AcademicRequestDetailResponse> {
  return apiRequest<AcademicRequestDetailResponse>(
    `/academic-requests/${encodeURIComponent(requestId)}`,
    { signal },
  );
}
