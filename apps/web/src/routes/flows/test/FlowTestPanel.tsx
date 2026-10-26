import { CircleAlert, Save } from "lucide-react";
import { useState } from "react";
import { Button } from "../../../components";
import { WebCallPanelLazy } from "./WebCallPanelLazy";

/**
 * Test tab (T070, FR-047): a browser test call on the saved draft. Unsaved changes are saved
 * first (or the operator cancels); a draft with errors cannot start a call.
 */
export function FlowTestPanel({
  agentId,
  dirty,
  errors,
  onSaveFirst,
  onStarted,
}: {
  agentId: string;
  dirty: boolean;
  errors: number;
  onSaveFirst: () => Promise<boolean>;
  onStarted: () => void;
}) {
  const [saving, setSaving] = useState(false);
  if (errors > 0)
    return (
      <div className="m-5 flex items-start gap-2.5 rounded-panel border border-danger/25 bg-danger-soft/40 px-4 py-3.5 text-[12.5px] leading-relaxed text-danger-text">
        <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        The draft has {errors} error{errors === 1 ? "" : "s"}. Fix them to place a test call; the Problems tab lists them.
      </div>
    );
  if (dirty)
    return (
      <div className="m-5 flex flex-col items-start gap-3 rounded-panel border border-line bg-surface-2/50 px-4 py-4">
        <p className="text-[12.5px] leading-relaxed text-fg-2">
          Test calls run the saved draft. Save your changes so the call runs exactly what is on the canvas.
        </p>
        <Button
          variant="primary"
          icon={<Save aria-hidden />}
          pending={saving}
          onClick={async () => {
            setSaving(true);
            await onSaveFirst();
            setSaving(false);
          }}
        >
          Save and test
        </Button>
      </div>
    );
  return (
    <div className="p-4" onPointerDownCapture={onStarted}>
      <WebCallPanelLazy agentId={agentId} version="draft" />
    </div>
  );
}
