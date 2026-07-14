import type { IsoDateTime, UUID } from './api';

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

// Roles supported by the backend in this phase. The frontend never uses the
// role as a security boundary — it only tailors what UI is offered; the
// backend authorizes every request.
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
