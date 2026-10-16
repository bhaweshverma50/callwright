import { cn } from "../../components";

export const MIN_PASSWORD = 10;

const COMMON = ["password", "1234567890", "qwerty", "letmein", "callwright", "welcome", "iloveyou", "admin"];

/** 0 to 4. Length carries most of the weight; variety and common words adjust it. */
export function passwordScore(pw: string): number {
  if (pw.length < MIN_PASSWORD) return pw.length === 0 ? 0 : 1;
  let s = 2;
  if (pw.length >= 14) s += 1;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
  if (classes >= 3) s += 1;
  if (COMMON.some((c) => pw.toLowerCase().includes(c)) || /^(.)\1+$/.test(pw)) s = Math.min(s, 1);
  return Math.min(4, s);
}

const LABELS = ["", "Too weak", "Fair", "Good", "Strong"];

/** Four-segment meter with a spoken label. Rule shown: at least 10 characters. */
export function PasswordStrength({ password, id }: { password: string; id?: string }) {
  const score = passwordScore(password);
  const tone = score <= 1 ? "bg-danger" : score === 2 ? "bg-warning" : "grad-action";
  return (
    <div id={id} className="flex items-center gap-3" aria-live="polite">
      <div className="flex flex-1 gap-1" aria-hidden>
        {[1, 2, 3, 4].map((i) => (
          <span key={i} className={cn("h-1 flex-1 rounded-full transition-colors", i <= score ? tone : "bg-surface-3")} />
        ))}
      </div>
      <span className="w-[120px] text-right text-[12px] text-fg-3">
        {password.length === 0
          ? `${MIN_PASSWORD}+ characters`
          : password.length < MIN_PASSWORD
            ? `${MIN_PASSWORD - password.length} more to go`
            : LABELS[score]}
      </span>
    </div>
  );
}
