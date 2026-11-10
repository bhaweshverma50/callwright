/**
 * Dismiss dialog (T052, FR-023): a reason, a note (required for "Other"), and for "Duplicate"
 * the other issue of the same agent that covers it. Dismissing a validating issue cancels the
 * validation; dismissed issues are hidden by default and never recreated by detection.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Archive } from "lucide-react";
import { useEffect, useState } from "react";
import { dismissIssue, issueKeys, useAgentIssues, type DetectedIssue, type DismissReason } from "../../api/issues";
import { Button, ChoiceGroup, Dialog, Field, ProblemAlert, Select, Textarea, toast } from "../../components";
import { DISMISS_REASONS } from "./shared";
import { bodyLimits } from "../../lib/contract.gen";

export function DismissDialog({ open, onOpenChange, issue }: { open: boolean; onOpenChange: (open: boolean) => void; issue: DetectedIssue }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState<DismissReason | null>(null);
  const [note, setNote] = useState("");
  const [duplicateOf, setDuplicateOf] = useState<string | undefined>(undefined);
  const [tried, setTried] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  const others = useAgentIssues(issue.agent_id, open && reason === "duplicate");

  useEffect(() => {
    if (open) return;
    setReason(null);
    setNote("");
    setDuplicateOf(undefined);
    setTried(false);
    setError(null);
  }, [open]);

  const candidates = (others.data ?? []).filter((i) => i.issue_id !== issue.issue_id);
  const errors = {
    reason: reason ? null : "Choose why you dismiss this issue.",
    note: reason === "other" && !note.trim() ? "Write a note that says why." : null,
    duplicate: reason === "duplicate" && !duplicateOf ? "Choose the issue that covers these failures." : null,
  };
  const invalid = Object.values(errors).some(Boolean);

  async function submit() {
    setTried(true);
    if (invalid || !reason) return;
    setPending(true);
    setError(null);
    try {
      await dismissIssue(issue.issue_id, {
        reason,
        note: note.trim() || null,
        ...(reason === "duplicate" && duplicateOf && { duplicate_of: duplicateOf }),
      });
      toast({ tone: "success", title: "Issue dismissed", description: "Later detections update its counts but keep it dismissed." });
      void qc.invalidateQueries({ queryKey: issueKeys.all });
      onOpenChange(false);
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="md"
      icon={<Archive aria-hidden />}
      title="Dismiss this issue"
      description={
        issue.status === "validating"
          ? "The running validation is cancelled. The issue is hidden from the list and later detections keep it dismissed."
          : "The issue is hidden from the list and later detections keep it dismissed."
      }
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" pending={pending} onClick={() => void submit()}>
            Dismiss issue
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <ProblemAlert error={error} kind="issue" className="[&>div]:mb-0" />
        <div className="flex flex-col gap-1.5">
          <span id="dismiss-reason" className="text-[13px] font-medium text-fg">
            Reason
          </span>
          <ChoiceGroup
            aria-labelledby="dismiss-reason"
            size="sm"
            columns={2}
            value={reason}
            onValueChange={setReason}
            options={DISMISS_REASONS.map((r) => ({ value: r.value, title: r.label, description: r.description }))}
          />
          {tried && errors.reason && (
            <p role="alert" className="text-[13px] text-danger-text">
              {errors.reason}
            </p>
          )}
        </div>
        {reason === "duplicate" && (
          <Field label="Duplicate of" error={tried ? errors.duplicate : null} hint="Another issue of the same agent.">
            {({ id, describedBy, invalid: bad }) => (
              <Select
                id={id}
                aria-label="Duplicate of"
                describedBy={describedBy}
                invalid={bad}
                value={duplicateOf}
                onValueChange={setDuplicateOf}
                placeholder={others.isPending ? "Loading issues" : candidates.length ? "Choose an issue" : "No other issues for this agent"}
                disabled={!candidates.length}
                options={candidates.map((c) => ({ value: c.issue_id, label: c.title }))}
              />
            )}
          </Field>
        )}
        <Field
          label={reason === "other" ? "Note" : "Note (optional)"}
          error={tried ? errors.note : null}
          hint="Up to 500 characters. Shown on the issue."
        >
          {({ id, describedBy, invalid: bad }) => (
            <Textarea
              id={id}
              aria-describedby={describedBy}
              aria-invalid={bad}
              maxLength={bodyLimits["POST /issues/{issue_id}/dismiss"].note.maxLength}
              className="min-h-[80px]"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}
