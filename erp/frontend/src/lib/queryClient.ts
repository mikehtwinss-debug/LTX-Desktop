import { MutationCache, QueryClient } from '@tanstack/react-query';

import { ApiError, type EntityId, errorMessage, isSessionExpiry, type QueryParams } from './api';
import { notify } from './notify';

const TRANSIENT_STATUSES = new Set([0, 502, 503, 504]);

/** One retry for failures that may pass by themselves; a 4xx answer will not change. */
function retryTransient(failureCount: number, error: unknown): boolean {
  return failureCount < 1 && error instanceof ApiError && TRANSIENT_STATUSES.has(error.status);
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: retryTransient,
      refetchOnWindowFocus: false,
    },
  },
  mutationCache: new MutationCache({
    // Every failed mutation is reported once here; forms additionally map field errors with
    // `applyApiErrorsToForm`. Session expiry is already announced by the API client.
    onError: (error) => {
      if (!isSessionExpiry(error)) {
        notify.error(errorMessage(error));
      }
    },
  }),
});

/**
 * Query key convention for resource endpoints. Keys start with the endpoint, so after a mutation
 * `queryClient.invalidateQueries({ queryKey: queryKeys.all('/mm/materials') })` refreshes every
 * list, select box and detail view of that resource.
 */
export const queryKeys = {
  all: (endpoint: string) => [endpoint] as const,
  list: (endpoint: string, params: QueryParams = {}) => [endpoint, 'list', params] as const,
  one: (endpoint: string, id: EntityId) => [endpoint, 'one', String(id)] as const,
};
