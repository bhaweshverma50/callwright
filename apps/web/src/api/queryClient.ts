import { QueryClient } from "@tanstack/react-query";
import { isApiError } from "./errors";

/**
 * One query client for the app (T026). Client errors (4xx) are not retried: they will not fix
 * themselves and a not-found should show at once. Network and 5xx get two quick retries.
 */
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        retry: (count, err) => {
          if (isApiError(err) && err.status >= 400 && err.status < 500) return false;
          return count < 2;
        },
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}

export const queryClient = createQueryClient();
