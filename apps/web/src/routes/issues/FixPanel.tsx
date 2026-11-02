/**
 * Fix panel (T034, US2): the current revision with its rationale and before/after, a kind picker
 * with the recommended kind first, guidance for the drafter, AI drafting and redrafting, a manual
 * edit that stores a new revision, and the revision history with each revision's status.
 */
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, FlaskConical, PenLine, Sparkles, Wand2 } from "lucide-react";
import { useState } from "react";
import {
  draftFixWithAi,
  issueKeys,
  saveManualFix,
  useIssueFixes,
  type DetectedIssue,
  type FixKind,
  type FixPayload,
  type FixRevision,
} from "../../api/issues";
import { useActionKey } from "../../api/paid";
import { Badge, Button, Field, Panel, Select, Textarea, cn, toast } from "../../components";
import { relative } from "../calls/format";
import { ProblemAlert } from "../simulations/shared";
import { EDITABLE, FixDiff } from "./FixDiff";
import { FixStatusBadge, KIND_HINTS, KIND_LABELS } from "./shared";

type Mode = "idle" | "draft" | "edit";

export function kindOptions(issue: Pick<DetectedIssue, "allowed_fix_kinds" | "recommended_fix_kind">) {
  const kinds = [issue.recommended_fix_kind, ...issue.allowed_fix_kinds.filter((k) => k !== issue.recommended_fix_kind)];
  return kinds.map((k) => ({
    value: k,
    label: k === issue.recommended_fix_kind ? `${KIND_LABELS[k]} (recommended)` : KIND_LABELS[k],
  }));
}

function Revision({ fix, current }: { fix: FixRevision; current?: boolean }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13.5px] font-semibold text-fg">
          {current ? "Current fix" : `Revision ${fix.revision}`}: {KIND_LABELS[fix.kind]}
        </span>
        <FixStatusBadge status={fix.status} />
        <Badge tone="neutral" icon={fix.source === "ai" ? <Sparkles aria-hidden /> : <PenLine aria-hidden />}>
          {fix.source === "ai" ? "Drafted by AI" : "Written by hand"}
        </Badge>
        <span className="text-[12px] text-fg-3">
          Revision {fix.revision}, {relative(fix.created_at)}
        </span>
      </div>
      {fix.rationale && <p className="max-w-[80ch] text-[13.5px] leading-relaxed text-fg-2">{fix.rationale}</p>}
      {fix.guidance && <p className="text-[12.5px] text-fg-3">Guidance: {fix.guidance}</p>}
      <FixDiff kind={fix.kind} payload={fix.payload} />
    </div>
  );
}

export function FixPanel({
  issue,
  onValidate,
  onDraftAndValidate,
}: {
  issue: DetectedIssue;
  onValidate: () => void;
  onDraftAndValidate: (draft: { kind: FixKind; guidance: string | null }) => void;
}) {
  const qc = useQueryClient();
  const fixes = useIssueFixes(issue.issue_id);
  const current = issue.current_fix ?? null;
  const [mode, setMode] = useState<Mode>(current ? "idle" : "draft");
  const [kind, setKind] = useState<FixKind>(issue.recommended_fix_kind);
  const [guidance, setGuidance] = useState("");
  const [text, setText] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState<"draft" | "save" | null>(null);
  const [openRevision, setOpenRevision] = useState<number | null>(null);
  const action = useActionKey();

  const closed = issue.status === "applied" || issue.status === "dismissed";
  const busy = issue.status === "validating";
  const editable = current ? EDITABLE[current.kind] : undefined;
  const advisory = current?.status === "advisory";

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: issueKeys.issue(issue.issue_id) });
    void qc.invalidateQueries({ queryKey: issueKeys.lists });
  };

  async function draft() {
    setPending("draft");
    setError(null);
    try {
      const fix = await draftFixWithAi(issue.issue_id, { kind, guidance: guidance.trim() || null }, action.current());
      action.reset();
      toast({
        tone: "success",
        title: `Revision ${fix.revision} drafted`,
        description: issue.status === "validated" ? "The issue is open again until this fix is validated." : undefined,
      });
      setMode("idle");
      setGuidance("");
      refresh();
    } catch (e) {
      setError(e);
    } finally {
      setPending(null);
    }
  }

  async function save() {
    if (!current || !editable) return;
    if (!text.trim()) {
      setError(null);
      return;
    }
    setPending("save");
    setError(null);
    try {
      const payload = { ...(current.payload as Record<string, unknown>), [editable.field]: text } as FixPayload;
      const fix = await saveManualFix(issue.issue_id, current.kind, payload);
      toast({ tone: "success", title: `Revision ${fix.revision} saved` });
      setMode("idle");
      refresh();
    } catch (e) {
      setError(e);
    } finally {
      setPending(null);
    }
  }

  function startEdit() {
    if (!current || !editable) return;
    setText(String((current.payload as Record<string, unknown>)[editable.field] ?? ""));
    setError(null);
    setMode("edit");
  }

  const history = (fixes.data ?? []).filter((f) => !f.is_current);

  return (
    <Panel
      title="Fix"
      description={
        closed
          ? "This issue is closed; its fixes are kept for reference."
          : busy
            ? "Validation is running. Drafting is paused until it finishes."
            : "Draft a change with AI or write it yourself. Every draft is kept as a revision."
      }
      icon={<Wand2 aria-hidden />}
    >
      <div className="flex flex-col gap-5">
        <ProblemAlert error={error} kind="issue" className="[&>div]:mb-0" />
        {current ? (
          <Revision fix={current} current />
        ) : (
          mode !== "draft" && <p className="text-[13.5px] text-fg-2">No fix yet. Draft one with AI or write it yourself.</p>
        )}

        {advisory && !closed && (
          <p className="text-[13px] text-warning-text">
            This fix is advice only, so it cannot be validated or applied. Add documents that cover these topics to a knowledge base, then draft
            another kind of fix.
          </p>
        )}

        {!closed && !busy && mode === "idle" && current && (
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={<FlaskConical aria-hidden />} disabled={advisory} onClick={onValidate}>
              {current.status === "passed" || current.status === "failed" || current.status === "inconclusive" ? "Validate again" : "Validate"}
            </Button>
            <Button icon={<Sparkles aria-hidden />} onClick={() => setMode("draft")}>
              Redraft
            </Button>
            {editable && (
              <Button icon={<PenLine aria-hidden />} onClick={startEdit}>
                Edit
              </Button>
            )}
          </div>
        )}

        {!closed && !busy && mode === "draft" && (
          <div className="flex flex-col gap-4 rounded-control border border-line p-4" role="group" aria-label="Draft a fix">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
              <Field label="Kind of fix" hint={KIND_HINTS[kind]}>
                {({ id }) => (
                  <Select id={id} aria-label="Kind of fix" value={kind} onValueChange={(v) => setKind(v as FixKind)} options={kindOptions(issue)} />
                )}
              </Field>
              <Field label="Guidance" hint="Optional. For example: keep the greeting unchanged.">
                {({ id, describedBy }) => (
                  <Textarea
                    id={id}
                    aria-describedby={describedBy}
                    className="min-h-[72px]"
                    maxLength={1000}
                    value={guidance}
                    onChange={(e) => setGuidance(e.target.value)}
                  />
                )}
              </Field>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" icon={<Sparkles aria-hidden />} pending={pending === "draft"} onClick={() => void draft()}>
                Draft fix
              </Button>
              <Button
                icon={<FlaskConical aria-hidden />}
                disabled={pending !== null}
                onClick={() => onDraftAndValidate({ kind, guidance: guidance.trim() || null })}
              >
                Draft and validate
              </Button>
              {current && (
                <Button variant="ghost" onClick={() => setMode("idle")}>
                  Cancel
                </Button>
              )}
            </div>
          </div>
        )}

        {!closed && !busy && mode === "edit" && editable && (
          <div className="flex flex-col gap-3 rounded-control border border-line p-4" role="group" aria-label="Edit the fix">
            <Field
              label={editable.label}
              hint="Saving stores a new revision written by hand. The current one is kept in the history."
              error={text.trim() ? null : "Enter the text of the fix."}
            >
              {({ id, describedBy, invalid }) => (
                <Textarea
                  id={id}
                  aria-describedby={describedBy}
                  aria-invalid={invalid}
                  className={cn("font-mono text-[12.5px]", current?.kind === "prompt_edit" ? "min-h-[220px]" : "min-h-[110px]")}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
              )}
            </Field>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" pending={pending === "save"} disabled={!text.trim()} onClick={() => void save()}>
                Save as new revision
              </Button>
              <Button variant="ghost" onClick={() => setMode("idle")}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {history.length > 0 && (
          <div className="flex flex-col gap-2 border-t border-line pt-4">
            <p className="text-[12.5px] text-fg-3">Earlier revisions</p>
            <ul className="flex flex-col divide-y divide-line rounded-control border border-line">
              {history.map((f) => {
                const open = openRevision === f.revision;
                return (
                  <li key={f.revision} className="flex flex-col">
                    <button
                      type="button"
                      aria-expanded={open}
                      onClick={() => setOpenRevision(open ? null : f.revision)}
                      className="flex w-full flex-wrap items-center gap-2 px-3 py-2.5 text-left text-[13px] hover:bg-surface-2"
                    >
                      <span className="font-medium text-fg">Revision {f.revision}</span>
                      <span className="text-fg-2">{KIND_LABELS[f.kind]}</span>
                      <FixStatusBadge status={f.status} />
                      <span className="ml-auto flex items-center gap-2 text-[12px] text-fg-3">
                        {relative(f.created_at)}
                        <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} aria-hidden />
                      </span>
                    </button>
                    {open && (
                      <div className="border-t border-line px-3 py-3">
                        <Revision fix={f} />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </Panel>
  );
}
