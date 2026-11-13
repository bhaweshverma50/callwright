import { useEffect } from "react";
import { signOut } from "../api/auth";
import { IDLE_LIMIT_MS, idleFor, touchActivity } from "../api/session";

const EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

/**
 * Signs out after IDLE_LIMIT_MS without input in any tab. Background polling keeps tokens fresh,
 * so the server alone cannot tell an open-but-abandoned tab from a person at work. Checked on
 * mount (a laptop reopened after a night), when the tab becomes visible, and every minute.
 */
export function useIdleSignOut(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    const check = () => {
      if (idleFor() > IDLE_LIMIT_MS) void signOut();
    };
    if (idleFor() === 0) touchActivity(true); // a session from before idle tracking starts now
    check();
    const onInput = () => touchActivity();
    const onVisible = () => document.visibilityState === "visible" && check();
    EVENTS.forEach((e) => window.addEventListener(e, onInput, { passive: true }));
    document.addEventListener("visibilitychange", onVisible);
    const timer = window.setInterval(check, 60_000);
    return () => {
      EVENTS.forEach((e) => window.removeEventListener(e, onInput));
      document.removeEventListener("visibilitychange", onVisible);
      window.clearInterval(timer);
    };
  }, [enabled]);
}
