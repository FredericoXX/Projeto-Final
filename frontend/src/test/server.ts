import { setupServer } from 'msw/node';
import { handlers } from './handlers';

// A single MSW server for the whole suite. No test ever hits the real network.
export const server = setupServer(...handlers);
