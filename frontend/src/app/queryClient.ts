import { QueryClient } from '@tanstack/react-query';
import { ApiError } from '../api/errors';

// Estados que representam erros determinísticos de cliente/permissão: repetir
// é inútil e, em /ask, executaria novamente uma pergunta silenciosamente.
const NON_RETRYABLE = new Set([401, 403, 404, 409, 422]);

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && NON_RETRYABLE.has(error.status)) {
            return false;
          }
          return failureCount < 1;
        },
      },
      mutations: {
        // Nunca repetir uma mutação automaticamente: /ask não pode ser reexecutado.
        retry: false,
      },
    },
  });
}
