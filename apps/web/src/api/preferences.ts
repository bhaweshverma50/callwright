/** Per-user preferences (spec 013): the guided setup tour's progress, saved on the server so it
 * follows the user across browsers. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { session } from "../app/session";
import { api, unwrap } from "./client";
import type { Onboarding, Preferences } from "./types";

export const preferencesKey = ["me", "preferences"] as const;

export function usePreferences() {
  return useQuery({
    queryKey: preferencesKey,
    queryFn: () => unwrap(api.GET("/me/preferences")) as Promise<Preferences>,
    enabled: session.isSignedIn(),
    staleTime: 5 * 60_000,
  });
}

export type OnboardingPatch = Partial<Pick<Onboarding, "status" | "step">>;

/**
 * Saves tour progress. The cache is updated first so the shell never waits on the request; a
 * failed save is only logged, because the tour keeps working locally and the next save carries
 * the full state again.
 */
export function useSaveOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: preferencesKey,
    mutationFn: (patch: OnboardingPatch) => unwrap(api.PATCH("/me/preferences", { body: { onboarding: patch } })) as Promise<Preferences>,
    onMutate: (patch) => {
      qc.setQueryData<Preferences>(preferencesKey, (old) =>
        old ? { onboarding: { ...old.onboarding, ...patch, updated_at: new Date().toISOString() } } : old,
      );
    },
    // An older response must not overwrite a newer optimistic state: only the last save in flight writes.
    onSuccess: (saved) => {
      if (qc.isMutating({ mutationKey: preferencesKey }) <= 1) qc.setQueryData(preferencesKey, saved);
    },
    onError: (e) => console.warn("Guided setup progress was not saved", e),
  });
}
