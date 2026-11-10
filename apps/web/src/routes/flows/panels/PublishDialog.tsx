import { CircleAlert, CircleCheck, Eye, Rocket, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { compileFlow, publishFlow, publishIssues, type CompileResult, type FlowValidationResult, type ValidationIssue } from "../../../api/flows";
import { problemMessage } from "../../../api/problems";
import { Button, Dialog, Field, Skeleton, Textarea, toast } from "../../../components";
import { CompilePreview } from "./CompilePreview";
import { bodyLimits } from "../../../lib/contract.gen";

/**
 * Publish (T045, FR-027): release notes, the warning count, and the errors that block it. The
 * compile preview shows what each step's model will receive.
 */
export function PublishDialog({
  open,
  onOpenChange,
  flowId,
  revision,
  validation,
  dirty,
  onPublished,
  onIssues,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  flowId: string;
  revision: number;
  validation: FlowValidationResult | null;
  dirty: boolean;
  onPublished: (versionNumber: number) => void;
  onIssues: (issues: ValidationIssue[]) => void;
}) {
  const [notes, setNotes] = useState("");
  const [pending, setPending] = useState(false);
  const [preview, setPreview] = useState<CompileResult | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const errors = validation?.errors ?? 0;
  const warnings = validation?.warnings ?? 0;

  const publish = async () => {
    setPending(true);
    try {
      const out = await publishFlow(flowId, revision, notes);
      toast({
        tone: "success",
        title: `Published version ${out.version_number}`,
        description: out.warnings ? `New calls use it. ${out.warnings} warning${out.warnings === 1 ? "" : "s"} remain.` : "New calls use it.",
      });
      setNotes("");
      onPublished(out.version_number);
      onOpenChange(false);
    } catch (e) {
      if (publishIssues(e).length) onIssues(publishIssues(e));
      toast({ tone: "error", title: "Not published", description: problemMessage(e, "flow") });
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      icon={<Rocket />}
      size="lg"
      title="Publish this flow"
      description="Publishing records a new version with the compiled flow. Calls already running keep their version."
      footer={
        <>
          <Button
            variant="ghost"
            icon={<Eye aria-hidden />}
            pending={previewing}
            disabled={dirty || errors > 0}
            onClick={async () => {
              setPreviewing(true);
              try {
                setPreview(await compileFlow(flowId));
              } finally {
                setPreviewing(false);
              }
            }}
          >
            Preview compiled flow
          </Button>
          <Button variant="primary" icon={<Rocket aria-hidden />} pending={pending} disabled={dirty || errors > 0} onClick={() => void publish()}>
            Publish
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {dirty && (
          <p className="flex items-start gap-2 rounded-control bg-warning-soft px-3 py-2.5 text-[13px] text-warning-text">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> Save your changes first; publishing uses the saved draft.
          </p>
        )}
        {errors > 0 ? (
          <p className="flex items-start gap-2 rounded-control bg-danger-soft px-3 py-2.5 text-[13px] text-danger-text">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {errors} error{errors === 1 ? "" : "s"} must be fixed before publishing.
            Open Problems in the side panel to find them.
          </p>
        ) : warnings > 0 ? (
          <p className="flex items-start gap-2 rounded-control bg-warning-soft/60 px-3 py-2.5 text-[13px] text-warning-text">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {warnings} warning{warnings === 1 ? "" : "s"}. You can publish; they are
            worth a look.
          </p>
        ) : validation ? (
          <p className="flex items-start gap-2 rounded-control bg-success-soft px-3 py-2.5 text-[13px] text-success-text">
            <CircleCheck className="mt-0.5 size-4 shrink-0" aria-hidden /> No problems found. The flow is ready to take calls.
          </p>
        ) : null}
        <Field label="Release notes (optional)" hint="Shown in the version history.">
          {({ id, describedBy }) => (
            <Textarea
              id={id}
              rows={3}
              maxLength={bodyLimits["POST /flows/{flow_id}/publish"].release_notes.maxLength}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              aria-describedby={describedBy}
            />
          )}
        </Field>
        {previewing && <Skeleton className="h-40 w-full" />}
        {preview && !previewing && <CompilePreview result={preview} />}
      </div>
    </Dialog>
  );
}
