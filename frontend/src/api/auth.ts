import { apiRequest } from './client';
import type { LoginRequest, TokenResponse, UserRead } from '../types/auth';

export function login(payload: LoginRequest, signal?: AbortSignal): Promise<TokenResponse> {
  return apiRequest<TokenResponse>('/auth/login', {
    method: 'POST',
    body: payload,
    signal,
  });
}

// GET /auth/me is the single source of truth for the current user; the JWT is
// never decoded on the client to make authorization decisions.
export function fetchCurrentUser(signal?: AbortSignal): Promise<UserRead> {
  return apiRequest<UserRead>('/auth/me', { signal });
}
