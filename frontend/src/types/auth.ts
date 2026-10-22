import type { IsoDateTime, UUID } from './api';

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

// Papéis suportados pelo backend nesta fase. O frontend nunca usa o papel como
// fronteira de segurança; apenas adapta a interface oferecida. O backend
// autoriza todos os pedidos.
export type UserRole = 'admin' | 'knowledge_manager' | 'staff' | 'student' | 'user';

// Permissões da matriz central do backend (app/core/permissions.py), devolvidas
// por GET /auth/me. A interface decide o que oferecer a partir desta lista, em
// vez de replicar no cliente a correspondência entre papéis e permissões.
export type Permission =
  | 'users.manage'
  | 'institution.manage'
  | 'external_identity.manage'
  | 'documents.manage'
  | 'conversations.system_messages'
  | 'academic_requests.read_own';

export interface UserRead {
  id: UUID;
  institution_id: UUID;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

// A conta autenticada, com as permissões efetivas do seu papel persistido.
export interface CurrentUserRead extends UserRead {
  permissions: Permission[];
}
