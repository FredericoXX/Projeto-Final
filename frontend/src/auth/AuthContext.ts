import { createContext } from 'react';
import type { CurrentUserRead, Permission } from '../types/auth';

export type AuthStatus = 'initializing' | 'authenticated' | 'unauthenticated';

export interface AuthContextValue {
  status: AuthStatus;
  user: CurrentUserRead | null;
  // Verdadeiro quando a conta autenticada tem a permissão indicada. Adapta a
  // interface; não é uma fronteira de segurança.
  can: (permission: Permission) => boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
