import { FileSpreadsheet, FileUp } from "lucide-react";
import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { problemMessage } from "../../../api/problems";
import { Button, Dialog, Field, Select, cn, focusRing } from "../../../components";
import { useDncImport, type DncImportResult } from "../hooks/useOutboundCompliance";

export const REGIONS = [
  { value: "none", label: "None (numbers include +country code)" },
  { value: "US", label: "United States (US)" },
  { value: "CA", label: "Canada (CA)" },
  { value: "GB", label: "United Kingdom (GB)" },
  { value: "IN", label: "India (IN)" },
  { value: "AU", label: "Australia (AU)" },
  { value: "DE", label: "Germany (DE)" },
  { value: "FR", label: "France (FR)" },
  { value: "ES", label: "Spain (ES)" },
  { value: "BR", label: "Brazil (BR)" },
  { value: "MX", label: "Mexico (MX)" },
  { value: "SG", label: "Singapore (SG)" },
  { value: "AE", label: "United Arab Emirates (AE)" },
];

const MAX_BYTES = 10 * 1024 * 1024;

/** Bulk do-not-call import from CSV (010 T078, FR-035): counts and the invalid rows. */
export function DncImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const run = useDncImport();
  const [file, setFile] = useState<File | null>(null);
  const [region, setRegion] = useState("none");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DncImportResult | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setFile(null);
    setError(null);
    setResult(null);
    run.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when opened
  }, [open]);

  const choose = (f: File | null) => {
    setError(null);
    setResult(null);
    if (f && f.size > MAX_BYTES) {
      setError("The file is over 10 MB. Split it and import each part.");
      return;
    }
    setFile(f);
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !run.isPending && onOpenChange(o)}
      icon={<FileSpreadsheet />}
      title="Import do-not-call numbers"
      description="A CSV with a header row and a number column; an optional note column is kept with each entry."
      footer={
        result ? (
          <Button variant="primary" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        ) : (
          <>
            <Button onClick={() => onOpenChange(false)} disabled={run.isPending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              pending={run.isPending}
              disabled={!file}
              onClick={() =>
                file &&
                run.mutate(
                  { file, region: region === "none" ? undefined : region },
                  { onSuccess: setResult, onError: (err) => setError(problemMessage(err, "file")) },
                )
              }
            >
              Import
            </Button>
          </>
        )
      }
    >
      {result ? (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-3">
          <dl className="grid grid-cols-3 gap-2">
            {[
              { label: "Added", value: result.imported, tone: "text-success-text" },
              { label: "Already listed", value: result.duplicates, tone: "text-fg" },
              { label: "Invalid", value: result.invalid_count, tone: result.invalid_count ? "text-danger-text" : "text-fg" },
            ].map((s) => (
              <div key={s.label} className="rounded-panel border border-line bg-surface-2/60 px-3 py-2.5">
                <dt className="text-[12px] text-fg-3">{s.label}</dt>
                <dd className={cn("font-mono text-[20px] tnum", s.tone)}>{s.value.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
          <p className="text-[13px] text-fg-3">{result.rows.toLocaleString()} rows read.</p>
          {result.invalid.length > 0 && (
            <div className="max-h-48 overflow-y-auto rounded-panel border border-line">
              <table className="w-full text-[13px]">
                <thead className="sticky top-0 bg-surface-2">
                  <tr className="text-left text-fg-3">
                    <th className="px-3 py-1.5 font-medium">Row</th>
                    <th className="px-3 py-1.5 font-medium">Value</th>
                    <th className="px-3 py-1.5 font-medium">Problem</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {result.invalid.map((r) => (
                    <tr key={r.row}>
                      <td className="px-3 py-1.5 font-mono tnum text-fg-2">{r.row}</td>
                      <td className="max-w-[140px] truncate px-3 py-1.5 font-mono text-fg">{r.value || "(empty)"}</td>
                      <td className="px-3 py-1.5 text-fg-2">{r.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </motion.div>
      ) : (
        <div className="flex flex-col gap-4">
          <button
            type="button"
            onClick={() => input.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              choose(e.dataTransfer.files[0] ?? null);
            }}
            className={cn(
              "group flex flex-col items-center gap-2 rounded-panel border border-dashed border-line-strong bg-surface-2/50 px-4 py-7 text-center transition-colors hover:border-accent/50 hover:bg-accent-soft/30",
              focusRing,
            )}
          >
            <span className="grid size-10 place-items-center rounded-control bg-accent-soft text-accent-text transition-[background-color,color] group-hover:bg-accent group-hover:text-white">
              <FileUp className="size-5" aria-hidden />
            </span>
            <span className="text-[14px] font-medium text-fg">{file ? file.name : "Choose a CSV file"}</span>
            <span className="text-[12px] text-fg-3">{file ? `${(file.size / 1024).toFixed(1)} KB` : "Up to 100,000 rows and 10 MB, UTF-8"}</span>
          </button>
          <input ref={input} type="file" accept=".csv,text/csv" hidden aria-label="CSV file" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
          <Field label="Default region" hint="For numbers written without a country code, such as (415) 555-0199.">
            {({ id, describedBy }) => <Select id={id} describedBy={describedBy} value={region} onValueChange={setRegion} options={REGIONS} />}
          </Field>
          {error && (
            <p role="alert" className="rounded-control bg-danger-soft px-3 py-2 text-[13px] text-danger-text">
              {error}
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
}
