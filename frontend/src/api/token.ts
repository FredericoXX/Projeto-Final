// O token de acesso reside apenas em sessionStorage (limpo ao fechar o
// separador). Nunca é escrito em localStorage, URLs, consultas ou logs.
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
      // Ignorar falhas de armazenamento; a sessão simplesmente não persiste.
    }
  },
  clear(): void {
    try {
      window.sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      // Ignorar.
    }
  },
};
