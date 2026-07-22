import { apiRequest } from './client';
import type { LoginRequest, TokenResponse, UserRead } from '../types/auth';

export function login(payload: LoginRequest, signal?: AbortSignal): Promise<TokenResponse> {
  return apiRequest<TokenResponse>('/auth/login', {
    method: 'POST',
    body: payload,
    signal,
  });
}

// GET /auth/me é a única fonte de verdade para o utilizador atual; o JWT nunca
// é decodificado no cliente para tomar decisões de autorização.
export function fetchCurrentUser(signal?: AbortSignal): Promise<UserRead> {
  return apiRequest<UserRead>('/auth/me', { signal });
}
