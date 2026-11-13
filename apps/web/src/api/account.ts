import { api, unwrap } from "./client";

/** Signed in: set a new password. The server ends every session and answers with a fresh one for this device. */
export function changePassword(currentPassword: string, newPassword: string) {
  return unwrap(api.POST("/auth/password", { body: { current_password: currentPassword, new_password: newPassword } }));
}

/** What the person typed to confirm deleting the account (the API checks each part). */
export interface DeletionConfirmation {
  confirmWorkspaceName: string;
  /** For an account with a password. */
  password?: string;
  /** For an account created through Google, which has none. */
  confirmEmail?: string;
}

/** Schedules deletion in 30 days and ends every session. */
export function scheduleAccountDeletion(c: DeletionConfirmation) {
  return unwrap(
    api.POST("/account/deletion", {
      body: {
        confirm_workspace_name: c.confirmWorkspaceName,
        ...(c.password !== undefined && { password: c.password }),
        ...(c.confirmEmail !== undefined && { confirm_email: c.confirmEmail }),
      },
    }),
  );
}

/** Keep the account: cancels a scheduled deletion. */
export async function cancelAccountDeletion() {
  await unwrap(api.DELETE("/account/deletion"));
}
