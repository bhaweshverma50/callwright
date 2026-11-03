import { useRef } from "react";

const TABBABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

function firstTabbable(root: Element | null): HTMLElement | null {
  if (!root) return null;
  for (const el of Array.from(root.querySelectorAll<HTMLElement>(TABBABLE))) {
    const visible = typeof el.checkVisibility === "function" ? el.checkVisibility() : !el.closest("[hidden]");
    if (visible && !el.closest("[inert], [aria-hidden='true']")) return el;
  }
  return null;
}

/** The element to return to: the focused one, or the trigger of the menu whose item opened us. */
function opener(): HTMLElement | null {
  const active = document.activeElement;
  if (!(active instanceof HTMLElement) || active === document.body) return null;
  const menu = active.closest<HTMLElement>("[role=menu]");
  if (menu?.id) {
    const trigger = document.querySelector<HTMLElement>(
      `[aria-controls="${typeof CSS !== "undefined" && CSS.escape ? CSS.escape(menu.id) : menu.id}"]`,
    );
    if (trigger) return trigger;
  }
  return active;
}

/**
 * Focus handling shared by Dialog and Drawer (002 T085).
 *
 * Opening: a control that took focus itself (`autoFocus`) keeps it; otherwise focus goes to the
 * first control in the body (`[data-dialog-body]`), then the footer, then the panel itself. Radix
 * would pick the header's close button, whose tooltip then swallows the first Escape.
 *
 * Closing: these dialogs open from state, not from a Radix trigger, so Radix has nothing to return
 * focus to and drops it on the page body. Focus goes back to the element that had it when the
 * dialog opened, unless the closing action already moved it somewhere on purpose (a jump to a
 * field from the error summary).
 */
export function useDialogFocus(open: boolean) {
  const returnTo = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  // Read while rendering the opening state: commit runs `autoFocus` before any effect, so this is
  // the last moment the opener still has focus.
  if (open && !wasOpen.current && typeof document !== "undefined") returnTo.current = opener();
  wasOpen.current = open;
  return {
    onOpenAutoFocus(event: Event) {
      event.preventDefault();
      const active = document.activeElement;
      const content = event.currentTarget as HTMLElement | null;
      if (content && active instanceof HTMLElement && content.contains(active)) return;
      const target =
        firstTabbable(content?.querySelector("[data-dialog-body]") ?? null) ??
        firstTabbable(content?.querySelector("[data-dialog-footer]") ?? null) ??
        content;
      target?.focus({ preventScroll: true });
    },
    onCloseAutoFocus(event: Event) {
      event.preventDefault();
      const target = returnTo.current;
      returnTo.current = null;
      const active = document.activeElement;
      const content = event.currentTarget as HTMLElement | null;
      const unclaimed = !active || active === document.body || Boolean(content?.contains(active));
      if (unclaimed && target?.isConnected) target.focus({ preventScroll: true });
    },
  };
}
