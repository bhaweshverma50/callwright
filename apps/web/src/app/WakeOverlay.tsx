import { useQueryClient } from "@tanstack/react-query";
import { RotateCw } from "lucide-react";
import { useEffect, useState } from "react";
import { WAKE_EXPECTED_MS, inlineWake, resetWake, useWakeState } from "../api/wakeGate";
import { Button, LogoLoader } from "../components";

/**
 * Full-page cover while the call servers start (hosted demo: the VM behind the API sleeps when
 * idle). Requests wait at the wake gate meanwhile, so pages underneath do not show errors. Shows
 * progress against the usual start time; after about three minutes it offers a retry.
 */
export function WakeOverlay() {
  const wake = useWakeState();
  const queryClient = useQueryClient();
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (wake.status !== "waking") return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [wake.status]);

  if (wake.status === "idle" || inlineWake.active) return null;

  if (wake.status === "failed") {
    return (
      <div
        role="alertdialog"
        aria-labelledby="wake-title"
        aria-describedby="wake-text"
        className="fixed inset-0 z-[100] grid place-items-center bg-bg px-4"
      >
        <div className="flex w-full max-w-[420px] flex-col items-center gap-4 text-center">
          <LogoLoader size="lg" still />
          <h1 id="wake-title" className="font-display text-[20px] font-semibold text-fg">
            The call servers did not start
          </h1>
          <p id="wake-text" className="text-[13.5px] text-fg-2">
            They usually take about a minute. Try again; if it keeps failing, the servers may be down for maintenance.
          </p>
          <Button
            variant="primary"
            icon={<RotateCw aria-hidden />}
            onClick={() => {
              resetWake();
              void queryClient.invalidateQueries();
            }}
          >
            Retry
          </Button>
        </div>
      </div>
    );
  }

  const elapsed = Math.max(0, now - wake.startedAt);
  const percent = Math.min(95, Math.round((elapsed / WAKE_EXPECTED_MS) * 100));
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="wake-title"
      aria-describedby="wake-text"
      className="fixed inset-0 z-[100] grid place-items-center bg-bg px-4"
    >
      <div className="flex w-full max-w-[420px] flex-col items-center gap-4 text-center">
        <LogoLoader size="lg" />
        <h1 id="wake-title" className="font-display text-[20px] font-semibold text-fg">
          Starting servers
        </h1>
        <p id="wake-text" className="text-[13.5px] text-fg-2">
          The call servers sleep when nobody is using them. Starting them takes about a minute; your request continues on its own.
        </p>
        <div
          role="progressbar"
          aria-label="Starting servers"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          className="h-1.5 w-full overflow-hidden rounded-full bg-surface-3"
        >
          <div className="grad-action h-full rounded-full transition-[width] duration-700 ease-out" style={{ width: `${percent}%` }} />
        </div>
      </div>
    </div>
  );
}
