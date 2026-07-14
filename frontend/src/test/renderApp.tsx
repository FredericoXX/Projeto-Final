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

// Renders the full application (all routes) starting at `initialPath`. Used for
// route-guard and end-to-end-style flows against MSW.
export function renderApp(initialPath = '/') {
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  return render(
    <Providers>
      <RouterProvider router={router} />
    </Providers>,
  );
}

// Renders an isolated element with all app providers and a memory router.
export function renderWithProviders(ui: ReactElement, initialPath = '/') {
  return render(
    <Providers>
      <MemoryRouter initialEntries={[initialPath]}>{ui}</MemoryRouter>
    </Providers>,
  );
}
