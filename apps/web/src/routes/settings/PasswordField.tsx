import { Eye, EyeOff } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Field, IconButton, Input } from "../../components";

/** A password field with a show and hide toggle, for the dialogs on the Settings page. */
export function PasswordField({
  label,
  value,
  onChange,
  error,
  hint,
  autoComplete,
  autoFocus,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
  hint?: ReactNode;
  autoComplete: "current-password" | "new-password";
  autoFocus?: boolean;
}) {
  const [shown, setShown] = useState(false);
  return (
    <Field label={label} error={error} hint={hint}>
      {({ id, describedBy, invalid }) => (
        <Input
          id={id}
          type={shown ? "text" : "password"}
          autoComplete={autoComplete}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby={describedBy}
          aria-invalid={invalid}
          autoFocus={autoFocus}
          spellCheck={false}
          suffix={
            <IconButton
              label={shown ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
              aria-pressed={shown}
              className="-mr-1.5 size-7"
              onClick={() => setShown((v) => !v)}
            >
              {shown ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
            </IconButton>
          }
        />
      )}
    </Field>
  );
}
