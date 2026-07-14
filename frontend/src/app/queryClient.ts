import { QueryClient } from '@tanstack/react-query';
import { ApiError } from '../api/errors';

// Statuses that are deterministic client/permission errors: retrying them is
// pointless and, for /ask, would silently re-run a question.
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
        // Never auto-retry a mutation — an /ask must never be replayed.
        retry: false,
      },
    },
  });
}
