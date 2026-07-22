import { setupServer } from 'msw/node';
import { handlers } from './handlers';

// Um único servidor MSW para toda a suite. Nenhum teste acede à rede real.
export const server = setupServer(...handlers);
