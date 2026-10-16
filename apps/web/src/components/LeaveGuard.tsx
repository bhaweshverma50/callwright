import { useEffect } from "react";
import { useBlocker } from "react-router";
import { ConfirmDialog } from "./Dialog";

/**
 * Unsaved-changes guard (FR-021, T085). While `when` is true:
 * - in-app navigation (links, back button) asks to stay or leave in a dialog;
 * - reload and tab close trigger the browser's own prompt via `beforeunload`.
 * Pass `when={dirty}` from any form, including never-saved create forms. Navigation that the
 * form itself starts after a successful save should flip `when` to false first.
 */
export function LeaveGuard({ when, message }: { when: boolean; message?: string }) {
  const blocker = useBlocker(({ currentLocation, nextLocation }) => when && currentLocation.pathname !== nextLocation.pathname);

  useEffect(() => {
    if (!when) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      // Legacy browsers need a returnValue; the text itself is not shown by modern browsers.
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [when]);

  return (
    <ConfirmDialog
      open={blocker.state === "blocked"}
      onOpenChange={(open) => {
        if (!open && blocker.state === "blocked") blocker.reset();
      }}
      title="Leave without saving?"
      description={message ?? "You have changes that are not saved. If you leave now they are discarded."}
      cancelLabel="Stay"
      confirmLabel="Leave"
      tone="danger"
      onConfirm={() => blocker.state === "blocked" && blocker.proceed()}
    />
  );
}
