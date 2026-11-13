import type { ReactNode } from "react";
import { Badge } from "../../components";
import { lastSignIn, type SignInMethod } from "../../lib/lastSignIn";

/** Wraps a sign-in button and pins a "Last used" badge to its corner when it matches. */
export function LastUsed({ method, children }: { method: SignInMethod; children: ReactNode }) {
  const used = lastSignIn() === method;
  return (
    <div className="relative">
      {children}
      {used && (
        <Badge tone="accent" className="pointer-events-none absolute -top-2.5 right-3 shadow-1">
          Last used
        </Badge>
      )}
    </div>
  );
}
