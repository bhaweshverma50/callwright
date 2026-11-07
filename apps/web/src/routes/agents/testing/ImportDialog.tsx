/**
 * Import dialog (US1, T041, FR-005, FR-006): pick or paste a JSON file in the
 * callwright.test_cases.v1 format (or a bare list), preview the outcome with a dry run, then
 * import. Rejected rows are listed by position and field; exact duplicates are skipped.
 */
import { useQueryClient } from "@tanstack/react-query";
import { Download, FileJson, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { downloadJson } from "../../../api/paid";
import { exportTestCases, importTestCases, testingKeys, type ImportOutcome, type TestCaseImportRow } from "../../../api/testing";
import { Button, Dialog, Field, Textarea, toast } from "../../../components";
import { FormAlert } from "../../public/FormAlert";
import { ProblemAlert, plural, problemText } from "../../simulations/shared";
import { bodyLimits } from "../../../lib/contract.gen";

export const MAX_IMPORT_ROWS = bodyLimits["POST /test-cases/import"].test_cases.maxItems;

/** Parses the wrapped format or a bare list; a message when the text is not usable. */
export function parseImport(text: string): { rows: TestCaseImportRow[] } | { error: string } {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { error: "This is not valid JSON. Check the file, or download the template for the format." };
  }
  const rows = Array.isArray(data) ? data : data && typeof data === "object" ? (data as { test_cases?: unknown }).test_cases : undefined;
  if (!Array.isArray(rows)) return { error: 'Expected a list of test cases, or an object with a "test_cases" list.' };
  if (rows.length === 0) return { error: "The file has no test cases." };
  if (rows.length > MAX_IMPORT_ROWS) return { error: `The file has ${rows.length.toLocaleString()} test cases. Import at most ${MAX_IMPORT_ROWS} at a time.` };
  return { rows: rows as TestCaseImportRow[] };
}

const FIELD_LABELS: Record<string, string> = {
  user_prompt: "caller says",
  expected_behaviour: "expected behaviour",
  category: "category",
  name: "name",
};

export function ImportDialog({ open, onOpenChange, agentId }: { open: boolean; onOpenChange: (open: boolean) => void; agentId: string }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ rows: TestCaseImportRow[]; outcome: ImportOutcome } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);

  const reset = () => {
    setPreview(null);
    setError(null);
    setParseError(null);
  };

  const check = async (source = text) => {
    reset();
    const parsed = parseImport(source);
    if ("error" in parsed) {
      setParseError(parsed.error);
      return;
    }
    setPending(true);
    try {
      setPreview({ rows: parsed.rows, outcome: await importTestCases(agentId, parsed.rows, true) });
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  };

  const doImport = async () => {
    if (!preview) return;
    setPending(true);
    setError(null);
    try {
      const res = await importTestCases(agentId, preview.rows, false);
      await qc.invalidateQueries({ queryKey: testingKeys.cases(agentId) });
      toast({
        tone: "success",
        title: `Imported ${plural(res.created, "test case")}`,
        ...((res.skipped_duplicates || res.errors.length) && {
          description: [
            res.skipped_duplicates ? `${plural(res.skipped_duplicates, "duplicate")} skipped` : "",
            res.errors.length ? `${plural(new Set(res.errors.map((e) => e.index)).size, "row")} rejected` : "",
          ]
            .filter(Boolean)
            .join(", "),
        }),
      });
      onOpenChange(false);
    } catch (e) {
      setError(e);
    } finally {
      setPending(false);
    }
  };

  const template = async () => {
    try {
      downloadJson("callwright_test_cases_template.json", await exportTestCases(agentId, true));
    } catch (e) {
      toast({ tone: "error", title: "Template did not download", description: problemText(e) });
    }
  };

  const o = preview?.outcome;
  const rejectedRows = o ? new Set(o.errors.map((e) => e.index)).size : 0;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      icon={<Upload aria-hidden />}
      title="Import test cases"
      description={`A JSON file of up to ${MAX_IMPORT_ROWS} test cases. Each needs what the caller says and the expected behaviour; name and category are optional.`}
      footer={
        <>
          <Button variant="ghost" icon={<Download aria-hidden />} onClick={() => void template()} className="mr-auto">
            Template
          </Button>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          {preview ? (
            <Button variant="primary" pending={pending} disabled={!o?.created} onClick={() => void doImport()}>
              {`Import ${plural(o?.created ?? 0, "test case")}`}
            </Button>
          ) : (
            <Button variant="primary" pending={pending} disabled={!text.trim()} onClick={() => void check()}>
              Check file
            </Button>
          )}
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept="application/json,.json"
            className="sr-only"
            aria-label="Choose a JSON file"
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const content = await file.text();
              setFileName(file.name);
              setText(content);
              e.target.value = "";
              void check(content);
            }}
          />
          <Button icon={<FileJson aria-hidden />} onClick={() => fileRef.current?.click()}>
            Choose file
          </Button>
          <span className="min-w-0 truncate text-[13px] text-fg-3">{fileName ?? "or paste the JSON below"}</span>
        </div>
        <Field label="JSON" hideLabel>
          {({ id }) => (
            <Textarea
              id={id}
              rows={6}
              spellCheck={false}
              className="font-mono text-[13px]"
              placeholder='{"format": "callwright.test_cases.v1", "test_cases": [{"user_prompt": "...", "expected_behaviour": "..."}]}'
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setFileName(null);
                reset();
              }}
            />
          )}
        </Field>
        {parseError && <FormAlert tone="error">{parseError}</FormAlert>}
        {o && (
          <section aria-label="Import preview" className="flex flex-col gap-3">
            <dl className="grid grid-cols-3 gap-3 rounded-control border border-line px-4 py-3">
              <div>
                <dt className="text-[12px] text-fg-3">Will be created</dt>
                <dd className="font-mono text-[18px] font-semibold text-fg tnum">{o.created}</dd>
              </div>
              <div>
                <dt className="text-[12px] text-fg-3">Duplicates skipped</dt>
                <dd className="font-mono text-[18px] font-semibold text-fg tnum">{o.skipped_duplicates}</dd>
              </div>
              <div>
                <dt className="text-[12px] text-fg-3">Rows rejected</dt>
                <dd
                  className={
                    rejectedRows ? "font-mono text-[18px] font-semibold text-danger-text tnum" : "font-mono text-[18px] font-semibold text-fg tnum"
                  }
                >
                  {rejectedRows}
                </dd>
              </div>
            </dl>
            {(o.errors.length > 0 || (o.duplicates?.length ?? 0) > 0) && (
              <ul className="max-h-48 divide-y divide-line overflow-y-auto rounded-control border border-line text-[13px]">
                {o.errors.map((e, i) => (
                  <li key={`e${i}`} className="flex gap-3 px-3 py-2">
                    <span className="w-14 shrink-0 font-mono text-fg-3 tnum">Row {e.index + 1}</span>
                    <span className="text-danger-text">
                      <span className="font-medium">{FIELD_LABELS[e.field] ?? e.field}</span>: {e.message}
                    </span>
                  </li>
                ))}
                {o.duplicates?.map((d) => (
                  <li key={`d${d}`} className="flex gap-3 px-3 py-2">
                    <span className="w-14 shrink-0 font-mono text-fg-3 tnum">Row {d + 1}</span>
                    <span className="text-fg-2">Skipped: same as an existing test case</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
        <ProblemAlert error={error} kind="test case" />
      </div>
    </Dialog>
  );
}
