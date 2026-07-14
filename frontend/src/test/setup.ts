import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { cleanup } from '@testing-library/react';
import { server } from './server';
import { tokenStorage } from '../api/token';

// Unhandled requests are an error: every test must mock exactly what it needs,
// and nothing ever escapes to the real network.
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));

afterEach(() => {
  cleanup();
  server.resetHandlers();
  tokenStorage.clear();
  window.sessionStorage.clear();
});

afterAll(() => server.close());
