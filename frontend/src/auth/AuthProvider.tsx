import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { fetchCurrentUser, login as loginRequest } from '../api/auth';
import { setUnauthorizedHandler } from '../api/client';
import { tokenStorage } from '../api/token';
import type { UserRead } from '../types/auth';
import { AuthContext, type AuthContextValue, type AuthStatus } from './AuthContext';

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>('initializing');
  const [user, setUser] = useState<UserRead | null>(null);

  const clearSession = useCallback(() => {
    tokenStorage.clear();
    setUser(null);
    setStatus('unauthenticated');
    queryClient.clear();
  }, [queryClient]);

  // A 401 anywhere in the app clears the session exactly once, centrally.
  useEffect(() => {
    setUnauthorizedHandler(clearSession);
    return () => setUnauthorizedHandler(null);
  }, [clearSession]);

  // Restore the session on load / refresh: /auth/me is the source of truth.
  useEffect(() => {
    const controller = new AbortController();
    const token = tokenStorage.get();
    if (!token) {
      setStatus('unauthenticated');
      return () => controller.abort();
    }
    fetchCurrentUser(controller.signal)
      .then((restored) => {
        setUser(restored);
        setStatus('authenticated');
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') {
          return;
        }
        tokenStorage.clear();
        setUser(null);
        setStatus('unauthenticated');
      });
    return () => controller.abort();
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const { access_token } = await loginRequest({ email, password });
      tokenStorage.set(access_token);
      try {
        const restored = await fetchCurrentUser();
        setUser(restored);
        setStatus('authenticated');
      } catch (error) {
        // A login is complete only after /auth/me validates the token and
        // supplies the authoritative role. Never retain a half-created session.
        clearSession();
        throw error;
      }
    },
    [clearSession],
  );

  const logout = useCallback(() => {
    clearSession();
  }, [clearSession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      isAdmin: user?.role === 'admin',
      login,
      logout,
    }),
    [status, user, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
