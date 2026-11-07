/**
 * Generate dialog (US1, T040, FR-033): drafts a few test cases with an LLM for one category or
 * all of them, with optional guidance. Out-of-range counts are corrected to the nearest bound as
 * typed. Drafts are reviewed here and only the kept ones are saved (through the import endpoint).
 * Drafting is charged once per action (Idempotency-Key).
 */
import { useQueryClient } from "@tanstack/react-query";
import { PenLine } from "lucide-react";
import { useState } from "react";
import { useActionKey, isRetryable } from "../../../api/paid";
import { generateTestCases, importTestCases, testingKeys, type TestCaseImportRow, type TestCategory } from "../../../api/testing";
import { Button, Dialog, Field, Input, Select, Textarea, ThinkingIndicator, cn, toast } from "../../../components";
import { ProblemAlert, cost, plural } from "../../simulations/shared";
import { ALL_CATEGORIES, CategoryLabel, categoryOptions } from "./categories";
import { bodyLimits } from "../../../lib/contract.gen";

const COUNT = bodyLimits["POST /test-cases/generate"].count;
export const MIN_COUNT = COUNT.minimum;
export const MAX_COUNT = COUNT.maximum;
const DEFAULT_COUNT = COUNT.default;

/** Typed text to the count shown: digits only, clamped to the allowed range; empty stays empty while typing. */
export function clampCount(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  if (digits === "") return "";
  return String(Math.min(MAX_COUNT, Math.max(MIN_COUNT, Number(digits))));
}

export const generateLabel = (n: number) => `Generate ${n} test ${n === 1 ? "case" : "cases"}`;

function DraftRow({
  draft,
  kept,
  onToggle,
  categories,
  index,
}: {
  draft: TestCaseImportRow;
  kept: boolean;
  onToggle: () => void;
  categories: TestCategory[];
  index: number;
}) {
  const id = `draft-${index}`;
  return (
    <li className={cn("flex gap-3 px-4 py-3 transition-opacity", !kept && "opacity-55")}>
      <input id={id} type="checkbox" checked={kept} onChange={onToggle} className="mt-1 size-4 shrink-0 cursor-pointer accent-[var(--accent)]" />
      <label htmlFor={id} className="flex min-w-0 flex-1 cursor-pointer flex-col gap-1.5">
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-[13px] font-medium text-fg">{draft.name ?? `Draft ${index + 1}`}</span>
          {draft.category && <CategoryLabel slug={draft.category} categories={categories} />}
        </span>
        <span className="text-[13px] text-fg">
          <span className="text-fg-3">Caller: </span>
          {draft.user_prompt}
        </span>
        <span className="text-[13px] text-fg-2">
          <span className="text-fg-3">Expected: </span>
          {draft.expected_behaviour}
        </span>
      </label>
    </li>
  );
}

export function GenerateDialog({
  open,
  onOpenChange,
  agentId,
  categories,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: string;
  categories: TestCategory[];
}) {
  const qc = useQueryClient();
  const key = useActionKey();
  const [category, setCategory] = useState(ALL_CATEGORIES);
  const [countText, setCountText] = useState(String(DEFAULT_COUNT));
  const [guidance, setGuidance] = useState("");
  const [drafts, setDrafts] = useState<TestCaseImportRow[] | null>(null);
  const [kept, setKept] = useState<boolean[]>([]);
  const [spent, setSpent] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  const count = countText === "" ? null : Number(countText);
  const keptCount = kept.filter(Boolean).length;
  const changed = () => key.reset();

  const generate = async () => {
    if (count === null) return;
    setPending(true);
    setError(null);
    try {
      const res = await generateTestCases(
        { agent_id: agentId, category: category === ALL_CATEGORIES ? null : category, count, guidance: guidance.trim() || null },
        key.current(),
      );
      key.reset();
      setDrafts(res.drafts);
      setKept(res.drafts.map(() => true));
      setSpent(res.cost_usd);
    } catch (e) {
      if (!isRetryable(e)) key.reset();
      setError(e);
    } finally {
      setPending(false);
    }
  };

  const save = async () => {
    if (!drafts) return;
    setPending(true);
    setError(null);
    try {
      const res = await importTestCases(
        agentId,
        drafts.filter((_, i) => kept[i]),
        false,
      );
      await qc.invalidateQueries({ queryKey: testingKeys.cases(agentId) });
      toast({
        tone: "success",
        title: `Saved ${plural(res.created, "test case")}`,
        ...(res.skipped_duplicates && { description: `${plural(res.skipped_duplicates, "duplicate")} skipped.` }),
      });
      onOpenChange(false);
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      icon={<PenLine aria-hidden />}
      title={drafts ? "Review drafted test cases" : "Generate test cases"}
      description={
        drafts
          ? `Untick the drafts you do not want. Nothing is saved until you save.${spent !== null ? ` Drafting cost ${cost(spent)}.` : ""}`
          : "Draft test cases from this agent's prompt and tools. Each generation is charged as a feature charge."
      }
      footer={
        drafts ? (
          <>
            <Button
              onClick={() => {
                setDrafts(null);
                setError(null);
              }}
            >
              Back
            </Button>
            <Button variant="primary" pending={pending} disabled={keptCount === 0} onClick={() => void save()}>
              {`Save ${plural(keptCount, "test case")}`}
            </Button>
          </>
        ) : (
          <>
            <Button onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button variant="primary" icon={<PenLine aria-hidden />} pending={pending} disabled={count === null} onClick={() => void generate()}>
              {count === null ? "Generate test cases" : generateLabel(count)}
            </Button>
          </>
        )
      }
    >
      {pending && !drafts ? (
        <ThinkingIndicator
          className="py-6"
          label="Drafting test cases"
          verbs={["Reading the agent", "Picking the weak spots", "Writing test cases", "Setting what good looks like"]}
        />
      ) : drafts ? (
        <div className="flex flex-col gap-3">
          <ul className="divide-y divide-line overflow-hidden rounded-control border border-line" aria-label="Drafts">
            {drafts.map((d, i) => (
              <DraftRow
                key={i}
                index={i}
                draft={d}
                categories={categories}
                kept={kept[i] ?? false}
                onToggle={() => setKept((k) => k.map((v, j) => (j === i ? !v : v)))}
              />
            ))}
          </ul>
          <ProblemAlert error={error} kind="test case" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-[minmax(0,1fr)_140px]">
            <Field label="Category" hint="All categories drafts a mix across every category.">
              {({ id, describedBy }) => (
                <Select
                  id={id}
                  describedBy={describedBy}
                  value={category}
                  onValueChange={(v) => {
                    setCategory(v);
                    changed();
                  }}
                  options={[{ value: ALL_CATEGORIES, label: "All categories" }, ...categoryOptions(categories)]}
                />
              )}
            </Field>
            <Field label="How many" hint={`${MIN_COUNT} to ${MAX_COUNT}`}>
              {({ id, describedBy }) => (
                <Input
                  id={id}
                  aria-describedby={describedBy}
                  inputMode="numeric"
                  value={countText}
                  onChange={(e) => {
                    setCountText(clampCount(e.target.value));
                    changed();
                  }}
                  onBlur={() => countText === "" && setCountText(String(MIN_COUNT))}
                />
              )}
            </Field>
          </div>
          <Field label="Guidance" hint="Optional. For example: callers who try to get a discount by pretending to be staff.">
            {({ id, describedBy }) => (
              <Textarea
                id={id}
                aria-describedby={describedBy}
                rows={3}
                maxLength={1000}
                value={guidance}
                onChange={(e) => {
                  setGuidance(e.target.value);
                  changed();
                }}
              />
            )}
          </Field>
          <ProblemAlert error={error} kind="test case" />
        </div>
      )}
    </Dialog>
  );
}
