/**
 * Apply and follow-up (T047, T053; US4, US5): why apply is not available yet, the apply
 * confirmation (publish now or create the version only), and for applied issues the version it
 * created with the headline pass rate on real calls before and after.
 */
import { useQueryClient } from "@tanstack/react-query";
import { GitBranchPlus, Rocket, TrendingUp } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { applyFix, issueKeys, type DetectedIssue } from "../../api/issues";
import { Button, deltaTone, Dialog, Field, Figure, Panel, ProblemAlert, Segmented, Textarea, toast } from "../../components";
import { BLOCKER_TEXT } from "./shared";
import { agentPath } from "../../lib/paths";
import { pct, pp, shortId, timeAgo } from "../../lib/format";
import { bodyLimits } from "../../lib/contract.gen";

function ApplyDialog({ open, onOpenChange, issue }: { open: boolean; onOpenChange: (o: boolean) => void; issue: DetectedIssue }) {
  const qc = useQueryClient();
  const [publish, setPublish] = useState<"publish" | "create">("publish");
  const [notes, setNotes] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function apply() {
    setPending(true);
    setError(null);
    try {
      const result = await applyFix(issue.issue_id, {
        fix_revision: issue.current_fix?.revision,
        publish: publish === "publish",
        release_notes_extra: notes.trim() || null,
      });
      const copies = result.tool_copies.length;
      toast({
        tone: "success",
        title: result.published ? "Fix applied and published" : "Version created",
        description: [
          result.published ? "New calls use the new version." : "Publish it from the agent's version history when you are ready.",
          copies ? `The tool was copied for this agent, so other agents keep the old description.` : "",
        ]
          .filter(Boolean)
          .join(" "),
      });
      qc.setQueryData(issueKeys.issue(issue.issue_id), result.issue);
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
      icon={<Rocket aria-hidden />}
      title="Apply this fix"
      description={`Creates a new version of the agent from exactly the configuration that passed validation. Its release notes read "Fix for ${issue.issue_id}: ${issue.title}".`}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" pending={pending} onClick={() => void apply()}>
            {publish === "publish" ? "Apply and publish" : "Create version"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <ProblemAlert error={error} kind="issue" className="[&>div]:mb-0" />
        <Field
          label="After creating the version"
          hint={
            publish === "publish" ? "New calls use it right away. Calls in progress keep their version." : "The published version stays as it is."
          }
        >
          {() => (
            <Segmented
              aria-label="After creating the version"
              value={publish}
              onValueChange={setPublish}
              options={[
                { value: "publish", label: "Publish it" },
                { value: "create", label: "Create version only" },
              ]}
            />
          )}
        </Field>
        <Field label="More release notes (optional)" hint="Added after the line that links the issue. Up to 500 characters.">
          {({ id, describedBy }) => (
            <Textarea
              id={id}
              aria-describedby={describedBy}
              maxLength={bodyLimits["POST /issues/{issue_id}/apply"].release_notes_extra.maxLength}
              className="min-h-[72px]"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          )}
        </Field>
      </div>
    </Dialog>
  );
}

export function ApplyPanel({ issue }: { issue: DetectedIssue }) {
  const [open, setOpen] = useState(false);
  if (issue.status === "dismissed") return null;

  if (issue.status === "applied") {
    const p = issue.post_apply;
    return (
      <Panel title="Applied" icon={<TrendingUp aria-hidden />} description={issue.applied_at ? `Applied ${timeAgo(issue.applied_at)}.` : undefined}>
        <div className="flex flex-col gap-4">
          {issue.applied_agent_version_id && (
            <p className="text-[14px] text-fg-2">
              The fix became version{" "}
              <Link
                to={agentPath({ id: issue.agent_id, type: issue.agent_type })}
                className="rounded-inline font-mono text-[13px] text-accent-text hover:underline"
                title={issue.applied_agent_version_id}
              >
                {shortId(issue.applied_agent_version_id)}
              </Link>{" "}
              of the agent.
            </p>
          )}
          {p?.ready ? (
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3" role="group" aria-label="Headline pass rate before and after">
              <Figure label="Before the fix" hint={`${p.before?.passes ?? 0} of ${p.before?.n ?? 0} real calls passed`}>
                {pct(p.before?.rate)}
              </Figure>
              <Figure label="After the fix" hint={`${p.after?.passes ?? 0} of ${p.after?.n ?? 0} real calls passed`}>
                {pct(p.after?.rate)}
              </Figure>
              <Figure label="Change">
                <span className={deltaTone(p.delta_pp)}>{pp(p.delta_pp)}</span>
              </Figure>
            </div>
          ) : (
            <p className="text-[13px] text-fg-3">
              The pass rate before and after is shown after 10 calls on the new version
              {p?.after ? ` (${p.after.n ?? 0} so far)` : ""}.
            </p>
          )}
        </div>
      </Panel>
    );
  }

  const blockers = (issue.apply_blockers ?? []).filter((b) => !(b === "wrong_status" && issue.apply_blockers!.length > 1));
  const lines =
    issue.status === "validating"
      ? ["Validation is running. Apply becomes available if the fix passes."]
      : (blockers.length ? blockers : (["no_passing_validation"] as const)).map((b) => BLOCKER_TEXT[b]);
  return (
    <Panel
      title="Apply"
      icon={<GitBranchPlus aria-hidden />}
      description="A passing fix becomes a new agent version with release notes that link back to this issue."
      actions={
        issue.can_apply ? (
          <Button variant="primary" size="sm" icon={<Rocket aria-hidden />} onClick={() => setOpen(true)}>
            Apply fix
          </Button>
        ) : undefined
      }
    >
      {issue.can_apply ? (
        <p className="text-[14px] text-fg-2">The current fix passed validation against the published version. Apply it to create the new version.</p>
      ) : (
        <ul className="flex flex-col gap-1.5 text-[14px] text-fg-2" aria-label="Why the fix cannot be applied yet">
          {lines.map((line) => (
            <li key={line} className="flex items-start gap-2">
              <span className="mt-[8px] size-1.5 shrink-0 rounded-full bg-fg-3" aria-hidden />
              {line}
            </li>
          ))}
        </ul>
      )}
      <ApplyDialog open={open} onOpenChange={setOpen} issue={issue} />
    </Panel>
  );
}
