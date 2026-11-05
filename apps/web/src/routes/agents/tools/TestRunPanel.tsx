import { useMutation } from "@tanstack/react-query";
import { CircleCheck, CircleX, FlaskConical, Play, Send, Variable } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type ReactNode } from "react";
import { testRunTool, type TestRunResult, type ToolDraft } from "../../../api/tools";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, Field, Textarea, cn } from "../../../components";
import { FormSection } from "./forms/FormSection";

const ERROR_LABELS: Record<string, string> = {
  timeout: "Timed out",
  http_status: "Error status",
  blocked_address: "Address blocked",
  invalid_arguments: "Invalid arguments",
  missing_variable: "Missing value",
  response_too_large: "Answer too large",
  connection_error: "Could not connect",
};

function Block({ label, children, mono = true }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <span className="text-[12px] font-medium text-fg-3">{label}</span>
      <div
        className={cn(
          "max-h-56 overflow-auto rounded-control border border-line bg-surface-2/70 px-3 py-2.5 text-[13px] leading-relaxed text-fg",
          mono && "whitespace-pre-wrap break-all font-mono",
        )}
      >
        {children}
      </div>
    </div>
  );
}

function pretty(text: string | null | undefined): string {
  if (!text) return "(empty)";
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch {
    return text;
  }
}

/**
 * Editor test run (T051): sample arguments and call variables in, then the status, timing, the
 * request as sent (secrets masked), the answer, mapped variables and exactly what the agent hears.
 */
export function TestRunPanel({
  toolId,
  draft,
  useSaved,
  initialArguments,
  disabled,
}: {
  toolId: string | null;
  draft: ToolDraft;
  /** Run the saved tool (stored secrets) rather than the form contents. */
  useSaved: boolean;
  initialArguments: Record<string, unknown>;
  disabled?: boolean;
}) {
  const [args, setArgs] = useState(() => JSON.stringify(initialArguments, null, 2));
  const [vars, setVars] = useState("{}");
  const parsed = (() => {
    try {
      const a = JSON.parse(args) as unknown;
      const v = JSON.parse(vars || "{}") as unknown;
      if (!a || typeof a !== "object" || Array.isArray(a)) return { error: "Arguments must be a JSON object." };
      if (!v || typeof v !== "object" || Array.isArray(v)) return { error: "Variables must be a JSON object." };
      return { a: a as Record<string, unknown>, v: v as Record<string, string> };
    } catch {
      return { error: "Not valid JSON." };
    }
  })();
  const run = useMutation({
    mutationFn: () =>
      testRunTool({
        ...(useSaved && toolId ? { tool_id: toolId } : { tool: draft }),
        arguments: parsed.a ?? {},
        dynamic_variables: parsed.v ?? {},
      }),
  });
  const result: TestRunResult | undefined = run.data;

  return (
    <FormSection
      title="Test run"
      icon={<FlaskConical aria-hidden />}
      description={
        useSaved
          ? "Runs the saved tool with its stored secrets. Free; up to 30 runs a minute."
          : "Runs what is in the form now. Free; up to 30 runs a minute."
      }
    >
      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 sm:grid-cols-2">
        <Field label="Arguments" error={"error" in parsed && parsed.error?.startsWith("Arguments") ? parsed.error : null}>
          {({ id }) => (
            <Textarea id={id} spellCheck={false} className="min-h-28 font-mono text-[13px]" value={args} onChange={(e) => setArgs(e.target.value)} />
          )}
        </Field>
        <Field label="Call variables" hint="Values for {{name}} that come from the call.">
          {({ id, describedBy }) => (
            <Textarea
              id={id}
              aria-describedby={describedBy}
              spellCheck={false}
              className="min-h-28 font-mono text-[13px]"
              value={vars}
              onChange={(e) => setVars(e.target.value)}
            />
          )}
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button icon={<Play aria-hidden />} pending={run.isPending} disabled={disabled || "error" in parsed} onClick={() => run.mutate()}>
          Run test
        </Button>
        {"error" in parsed && <span className="text-[13px] text-danger-text">{parsed.error}</span>}
        {run.isError && <span className="text-[13px] text-danger-text">{problemMessage(run.error, "tool")}</span>}
      </div>
      <AnimatePresence mode="wait">
        {result && (
          <motion.div
            key={run.submittedAt}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22 }}
            className="flex flex-col gap-3 rounded-panel border border-line bg-surface p-4 shadow-1"
            aria-live="polite"
          >
            <div className="flex flex-wrap items-center gap-2">
              {result.is_error ? (
                <Badge tone="danger" icon={<CircleX />}>
                  {ERROR_LABELS[result.error_code ?? ""] ?? "Failed"}
                </Badge>
              ) : (
                <Badge tone="success" icon={<CircleCheck />}>
                  Succeeded
                </Badge>
              )}
              {result.http_status != null && <Badge>HTTP {result.http_status}</Badge>}
              <Badge tone="accent">{result.duration_ms.toLocaleString()} ms</Badge>
              {result.error_message && <span className="text-[13px] text-fg-2">{result.error_message}</span>}
            </div>
            {result.request?.url && (
              <Block label="Request sent">
                <span className="text-accent-text">{result.request.method}</span> {result.request.url}
                {Object.entries(result.request.headers ?? {}).map(([k, v]) => `\n${k}: ${v}`)}
                {result.request.body != null && `\n\n${JSON.stringify(result.request.body, null, 2)}`}
              </Block>
            )}
            {result.response_body != null && <Block label="Answer">{pretty(result.response_body)}</Block>}
            {Object.keys(result.mapped_variables ?? {}).length > 0 && (
              <div className="flex flex-col gap-1.5">
                <span className="text-[12px] font-medium text-fg-3">Mapped variables</span>
                <dl className="divide-y divide-line rounded-control border border-line">
                  {Object.entries(result.mapped_variables ?? {}).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between gap-3 px-3 py-2 text-[13px]">
                      <dt className="flex items-center gap-1.5 font-mono text-fg">
                        <Variable className="size-3.5 text-fg-3" aria-hidden />
                        {k}
                      </dt>
                      <dd className="min-w-0 truncate font-mono text-fg-2">{typeof v === "string" ? v : JSON.stringify(v)}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
            {(result.missing_paths ?? []).length > 0 && (
              <p className="text-[13px] text-warning-text">Not found in the answer: {(result.missing_paths ?? []).join(", ")}</p>
            )}
            <Block label="What the agent hears">
              <span className="inline-flex items-start gap-2">
                <Send className="mt-0.5 size-3.5 shrink-0 text-accent-text" aria-hidden />
                <span>{result.llm_payload}</span>
              </span>
            </Block>
          </motion.div>
        )}
      </AnimatePresence>
    </FormSection>
  );
}
