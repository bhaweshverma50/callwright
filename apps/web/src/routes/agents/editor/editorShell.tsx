/**
 * What the single-prompt editor and the flow builder share around their drafts: both catalogs
 * loaded once, one way to show a record that did not load, and Cmd or Ctrl + S.
 */
import { useEffect, useMemo, type ReactNode } from "react";
import { useLlmCatalog, useVoiceCatalog } from "../../../api/agents";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { EmptyState } from "../../../components";
import { AGENTS_PATH } from "../../../lib/paths";
import { RecordNotFound } from "../../NotFound";
import type { Catalogs } from "./catalogs";

/** The model and voice catalogs, once both have loaded. */
export function useCatalogs(): { catalogs: Catalogs | null; error: unknown } {
  const llm = useLlmCatalog();
  const voice = useVoiceCatalog();
  const catalogs = useMemo(() => (llm.data && voice.data ? { llm: llm.data, voice: voice.data } : null), [llm.data, voice.data]);
  return { catalogs, error: llm.error ?? voice.error };
}

/** A missing agent reads as not found; any other failure says what did not load. */
export function LoadFailure({ error, icon, what }: { error: unknown; icon: ReactNode; what: "agent" | "flow" }) {
  if (isApiError(error) && error.status === 404) return <RecordNotFound kind="agent" backTo={AGENTS_PATH} backLabel="Back to Agents" />;
  return (
    <EmptyState icon={icon} title={`The ${what} did not load`}>
      {problemMessage(error, what)}
    </EmptyState>
  );
}

export function useSaveShortcut(save: () => void, enabled: boolean) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (enabled) save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, enabled]);
}
