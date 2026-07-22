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
export type UserRole = 'admin' | 'staff' | 'student' | 'user';

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
