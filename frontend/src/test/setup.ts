import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { cleanup } from '@testing-library/react';
import { server } from './server';
import { tokenStorage } from '../api/token';

// Pedidos não tratados são erros: cada teste deve simular exatamente o que
// precisa, e nada pode alcançar a rede real.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));

afterEach(() => {
  cleanup();
  server.resetHandlers();
  tokenStorage.clear();
  window.sessionStorage.clear();
});

afterAll(() => server.close());
