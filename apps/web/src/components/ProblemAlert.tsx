import { Link } from "react-router";
import { isInsufficientCredit } from "../api/paid";
import { isApiError } from "../api/errors";
import { problemMessage, problemText } from "../api/problems";
import { BILLING_PATH } from "../lib/paths";
import { Button } from "./Button";
import { FormAlert } from "./FormAlert";

/**
 * A failed request above a form or a panel, worded by problemText (a 422 keeps the general
 * wording: its details belong next to the fields). A 402 also links to Billing.
 */
export function ProblemAlert({ error, kind = "record", className }: { error: unknown; kind?: string; className?: string }) {
  if (!error) return null;
  const credit = isInsufficientCredit(error);
  return (
    <div className={className}>
      <FormAlert
        tone={credit ? "warning" : "error"}
        action={
          credit ? (
            <Button asChild size="sm" variant="secondary" className="w-fit">
              <Link to={BILLING_PATH}>Add funds</Link>
            </Button>
          ) : undefined
        }
      >
        {isApiError(error) && error.status === 422 ? problemMessage(error, kind) : problemText(error, kind)}
      </FormAlert>
    </div>
  );
}
