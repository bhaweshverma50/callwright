import { KeyRound, RefreshCw, Undo2 } from "lucide-react";
import { useState } from "react";
import { Button, Input } from "../../../../components";

/**
 * Value of a secret header (T050). A stored secret shows only its mask (last four characters) and
 * a Replace action; typing a new value replaces it on save. The value is never read back.
 */
export function SecretHeaderInput({
  id,
  masked,
  value,
  invalid,
  describedBy,
  onChange,
}: {
  id?: string;
  /** Mask of the stored secret, when one exists. */
  masked: string | null | undefined;
  value: string | null | undefined;
  invalid?: boolean;
  describedBy?: string;
  onChange: (value: string | null) => void;
}) {
  const [replacing, setReplacing] = useState(!masked);
  if (masked && !replacing) {
    return (
      <div className="flex h-9 min-w-0 items-center gap-2 rounded-control border border-line bg-surface-2 pl-3 pr-1">
        <KeyRound className="size-4 shrink-0 text-fg-3" aria-hidden />
        <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-fg-2" aria-label="Stored secret">
          {masked}
        </span>
        <Button size="sm" variant="ghost" icon={<RefreshCw aria-hidden />} onClick={() => setReplacing(true)}>
          Replace
        </Button>
      </div>
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <Input
        id={id}
        type="password"
        autoComplete="new-password"
        className="min-w-0 flex-1 font-mono"
        prefix={<KeyRound aria-hidden />}
        placeholder={masked ? "New secret value" : "Secret value"}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      />
      {masked && (
        <Button
          size="sm"
          variant="ghost"
          icon={<Undo2 aria-hidden />}
          onClick={() => {
            onChange(null);
            setReplacing(false);
          }}
        >
          Keep
        </Button>
      )}
    </div>
  );
}
