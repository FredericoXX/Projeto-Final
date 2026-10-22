import { useQuery } from '@tanstack/react-query';
import {
  getAcademicRequest,
  getAcademicRequestsAccess,
  listAcademicRequests,
} from '../../api/academicRequests';
import { useAuth } from '../../auth/useAuth';

export const academicRequestKeys = {
  access: ['academic-requests', 'access'] as const,
  list: ['academic-requests', 'list'] as const,
  detail: (requestId: string) => ['academic-requests', 'detail', requestId] as const,
};

// Sem refetch automático nem polling: a consulta à fonte institucional só
// acontece quando o utilizador abre a área ou pede para tentar de novo.
const USER_INITIATED = {
  refetchOnWindowFocus: false,
  refetchOnReconnect: false,
  refetchInterval: false,
  retry: false,
} as const;

// Só pergunta ao backend pela disponibilidade quando o papel tem a permissão:
// as restantes contas nunca veem a área nem originam o pedido.
export function useAcademicRequestsAccess() {
  const { status, can } = useAuth();
  const enabled = status === 'authenticated' && can('academic_requests.read_own');
  return useQuery({
    queryKey: academicRequestKeys.access,
    queryFn: ({ signal }) => getAcademicRequestsAccess(signal),
    enabled,
    ...USER_INITIATED,
  });
}

export function useAcademicRequests() {
  return useQuery({
    queryKey: academicRequestKeys.list,
    queryFn: ({ signal }) => listAcademicRequests(signal),
    ...USER_INITIATED,
  });
}

export function useAcademicRequest(requestId: string) {
  return useQuery({
    queryKey: academicRequestKeys.detail(requestId),
    queryFn: ({ signal }) => getAcademicRequest(requestId, signal),
    ...USER_INITIATED,
  });
}
