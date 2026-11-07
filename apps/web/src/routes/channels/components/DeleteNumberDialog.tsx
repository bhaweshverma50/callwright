import { Hourglass, Trash2 } from "lucide-react";
import { useState } from "react";
import { isApiError, problemAs } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { Button, Dialog, OnAir } from "../../../components";

/**
 * Delete a number or WhatsApp channel (010 T044, FR-012, FR-030). With live calls the only way is
 * "Delete when idle": new calls stop now, the live ones finish, and it is removed afterwards.
 */
export function DeleteNumberDialog({
  open,
  onOpenChange,
  what,
  name,
  activeCalls,
  onDelete,
  pending,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  /** "number" or "WhatsApp channel". */
  what: string;
  name: string;
  activeCalls: number;
  onDelete: (whenIdle: boolean) => Promise<unknown>;
  pending: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  const [count, setCount] = useState<number | null>(null);
  const live = count ?? activeCalls;

  const run = async (whenIdle: boolean) => {
    setError(null);
    try {
      await onDelete(whenIdle);
      onOpenChange(false);
    } catch (err) {
      if (isApiError(err) && err.status === 409) {
        const n = problemAs(err, "ActiveCallsProblem")?.active_call_count;
        if (n) {
          setCount(n);
          return;
        }
      }
      setError(problemMessage(err, what));
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (pending) return;
        setError(null);
        setCount(null);
        onOpenChange(o);
      }}
      role="alertdialog"
      size="sm"
      icon={live ? <Hourglass /> : <Trash2 />}
      title={live ? `Delete ${name} when idle?` : `Delete ${name}?`}
      description={
        live
          ? `New calls stop right away. The ${live === 1 ? "live call finishes" : `${live} live calls finish`} undisturbed, then the ${what} is removed.`
          : `Calls to it stop and its routing is removed. Past calls keep showing the ${what} and its label.`
      }
      footer={
        <>
          <Button autoFocus onClick={() => onOpenChange(false)} disabled={pending}>
            Cancel
          </Button>
          <Button variant="danger" pending={pending} onClick={() => void run(live > 0)}>
            {live ? "Delete when idle" : `Delete ${what}`}
          </Button>
        </>
      }
    >
      {live > 0 && <OnAir label={`${live} live ${live === 1 ? "call" : "calls"} on this ${what}`} />}
      {error && (
        <p role="alert" className="mt-2 rounded-control bg-danger-soft px-3 py-2 text-[13px] text-danger-text">
          {error}
        </p>
      )}
    </Dialog>
  );
}
