import { Link } from "react-router";
import { isApiError } from "../api/errors";
import { isInsufficientCredit } from "../api/paid";
import { problemMessage } from "../api/problems";
import { BILLING_PATH } from "../lib/paths";
import { Button } from "./Button";
import { FormAlert } from "./FormAlert";

/**
 * A failed request above a form or a panel. A 402 says how to add funds and links to Billing;
 * other problems show the server's `detail` when it sent one.
 */
export function ProblemAlert({ error, kind = "record", className }: { error: unknown; kind?: string; className?: string }) {
  if (!error) return null;
  if (isInsufficientCredit(error)) {
    return (
      <div className={className}>
        <FormAlert
          tone="warning"
          action={
            <Button asChild size="sm" variant="secondary" className="w-fit">
              <Link to={BILLING_PATH}>Add funds</Link>
            </Button>
          }
        >
          Your balance is too low to start paid work. Add funds to continue.
        </FormAlert>
      </div>
    );
  }
  const detail = isApiError(error) && error.status !== 422 && error.problem.detail ? error.problem.detail : null;
  return (
    <div className={className}>
      <FormAlert tone="error">{detail ?? problemMessage(error, kind)}</FormAlert>
    </div>
  );
}

/** Message for a toast: same rules as ProblemAlert, as text. */
export function problemText(error: unknown, kind = "record"): string {
  if (isInsufficientCredit(error)) return "Your balance is too low. Add funds on the Billing page to continue.";
  if (isApiError(error) && error.problem.detail) return error.problem.detail;
  return problemMessage(error, kind);
}
