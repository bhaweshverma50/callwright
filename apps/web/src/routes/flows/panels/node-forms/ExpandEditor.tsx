import { Maximize2 } from "lucide-react";
import { useState } from "react";
import { Button, Dialog, IconButton, Textarea } from "../../../../components";

/**
 * A multiline field with an expanded editor (FR-057): the side panel keeps a short textarea and
 * the expand button opens the same text in a large dialog.
 */
export function ExpandEditor({
  id,
  label,
  value,
  onChange,
  rows = 5,
  placeholder,
  describedBy,
  invalid,
  maxLength,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
  placeholder?: string;
  describedBy?: string;
  invalid?: boolean;
  maxLength?: number;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <Textarea
        id={id}
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-describedby={describedBy}
        aria-invalid={invalid || undefined}
        maxLength={maxLength}
        className="pr-10"
      />
      <IconButton label={`Expand ${label.toLowerCase()}`} className="absolute right-1.5 top-1.5 size-7" onClick={() => setOpen(true)}>
        <Maximize2 className="size-3.5" aria-hidden />
      </IconButton>
      <Dialog open={open} onOpenChange={setOpen} title={label} size="lg" footer={<Button onClick={() => setOpen(false)}>Done</Button>}>
        <Textarea
          aria-label={label}
          autoFocus
          rows={18}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          maxLength={maxLength}
          className="font-mono text-[13px] leading-relaxed"
        />
        {maxLength ? (
          <p className="mt-2 text-right font-mono text-[11.5px] text-fg-3 tnum">
            {value.length.toLocaleString()} / {maxLength.toLocaleString()}
          </p>
        ) : null}
      </Dialog>
    </div>
  );
}
