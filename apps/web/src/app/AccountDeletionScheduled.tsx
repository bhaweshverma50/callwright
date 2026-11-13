import { Hourglass } from "@phosphor-icons/react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogOut, ShieldCheck } from "lucide-react";
import { cancelAccountDeletion } from "../api/account";
import { signOut } from "../api/auth";
import { problemText } from "../api/problems";
import { qk } from "../api/queries";
import type { Me } from "../api/types";
import { Button, EmptyState, Logo, MoneyText, toast } from "../components";
import { dateLabel } from "../lib/format";

/**
 * What a signed-in person sees while their account is scheduled for deletion, in place of the app:
 * the API refuses every other call until they keep the account. Keeping it cancels the deletion
 * and goes back into the app.
 */
export function AccountDeletionScheduled({ me, scheduledAt }: { me: Me; scheduledAt: string }) {
  const qc = useQueryClient();
  const keep = useMutation({
    mutationFn: cancelAccountDeletion,
    onSuccess: () => {
      qc.setQueryData<Me>(qk.me, (old) => (old ? { ...old, user: { ...old.user, deletion_scheduled_at: null } } : old));
      toast({ tone: "success", title: "Account kept", description: "Your account will not be deleted." });
    },
  });
  return (
    <div className="flex min-h-dvh flex-col bg-bg px-5 py-6 sm:px-12">
      <Logo />
      <main id="main" tabIndex={-1} className="flex flex-1 items-center py-12 outline-none">
        <EmptyState
          icon={<Hourglass weight="duotone" />}
          title={`Your account is scheduled for deletion on ${dateLabel(scheduledAt)}`}
          actions={
            <>
              <Button variant="primary" size="lg" pending={keep.isPending} icon={<ShieldCheck aria-hidden />} onClick={() => keep.mutate()}>
                Keep my account
              </Button>
              <Button size="lg" variant="ghost" icon={<LogOut aria-hidden />} onClick={() => void signOut()}>
                Sign out
              </Button>
            </>
          }
        >
          <p>
            On that day the {me.workspace.name} workspace is erased: agents, calls, recordings and knowledge, and your phone numbers are released.
            Your remaining balance of <MoneyText value={me.balance_usd} places={3} className="font-medium" /> is forfeited and cannot be refunded.
          </p>
          <p className="mt-2">Keep your account to cancel the deletion and carry on where you left off. Until then nothing else is available.</p>
          {keep.error && (
            <p role="alert" className="mt-3 text-[13px] text-danger-text">
              {problemText(keep.error)}
            </p>
          )}
        </EmptyState>
      </main>
    </div>
  );
}
