import type { ReactElement, ReactNode } from 'react';
import { render } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router-dom';
import { I18nProvider } from '../i18n/I18nProvider';
import { AuthProvider } from '../auth/AuthProvider';
import { createQueryClient } from '../app/queryClient';
import { routes } from '../app/router';

function Providers({ children }: { children: ReactNode }) {
  const queryClient = createQueryClient();
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AuthProvider>{children}</AuthProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}

// Renderiza a aplicação completa (todas as rotas) a partir de `initialPath`.
// Usado em proteções de rota e fluxos completos simulados com MSW.
export function renderApp(initialPath = '/') {
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  return render(
    <Providers>
      <RouterProvider router={router} />
    </Providers>,
  );
}

// Renderiza um elemento isolado com todos os provedores e um roteador em memória.
export function renderWithProviders(ui: ReactElement, initialPath = '/') {
  return render(
    <Providers>
      <MemoryRouter initialEntries={[initialPath]}>{ui}</MemoryRouter>
    </Providers>,
  );
}
