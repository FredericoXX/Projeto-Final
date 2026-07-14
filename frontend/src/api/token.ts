// The access token lives in sessionStorage only (cleared when the tab
// closes). It is never written to localStorage, URLs, query strings or logs.
const TOKEN_KEY = 'institutional_assistant_access_token';

export const tokenStorage = {
  get(): string | null {
    try {
      return window.sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string): void {
    try {
      window.sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      // Ignore storage failures; the session simply won't persist.
    }
  },
  clear(): void {
    try {
      window.sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      // Ignore.
    }
  },
};
