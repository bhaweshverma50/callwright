import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Activity, CircleAlert, CircleCheck, Cloud, Database, Link2, Plug, RefreshCw, ShieldCheck, Table2, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import {
  CONNECT_RETURN_KEY,
  SCOPE_LABELS,
  connectionKeys,
  deleteConnection,
  startGoogleConnection,
  testConnection,
  useConnection,
  useConnections,
  type Connection,
  type ConnectionUser,
} from "../../../api/connections";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, ConfirmDialog, EmptyState, Fact, FactGrid, PageHeader, Panel, Skeleton, toast, type Tone } from "../../../components";
import { timeAgo } from "../../../lib/format";
import { CONNECTIONS_PATH, knowledgeBasePath } from "../../../lib/paths";

const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly";

const HEALTH: Record<Connection["health"], { label: string; tone: Tone; icon: ReactNode }> = {
  healthy: { label: "Healthy", tone: "success", icon: <CircleCheck /> },
  failing: { label: "Failing", tone: "warning", icon: <CircleAlert /> },
  revoked: { label: "Revoked", tone: "danger", icon: <CircleAlert /> },
};

/** Sends the browser to Google; the callback page brings it back. */
export function useStartConnect() {
  return useMutation({
    mutationFn: (connectionId?: string) => startGoogleConnection(connectionId),
    onSuccess: ({ authorization_url }) => {
      try {
        sessionStorage.setItem(CONNECT_RETURN_KEY, window.location.pathname + window.location.search);
      } catch {
        // Storage can be unavailable (private windows); the callback falls back to Connections.
      }
      window.location.assign(authorization_url);
    },
    onError: (err) => toast({ tone: "error", title: "Could not start Google sign-in", description: problemMessage(err, "connection") }),
  });
}

/**
 * Settings > Connections (022 US1): Google accounts the workspace syncs knowledge from. Each card
 * shows the account, the access granted, health and the knowledge bases using it.
 */
export function ConnectionsPage() {
  const list = useConnections();
  const connect = useStartConnect();
  const configured = list.data?.google_configured ?? true;
  const items = list.data?.items ?? [];
  return (
    <>
      <PageHeader
        title="Connections"
        description="Google accounts Callwright reads from. Knowledge bases sync their documents through these; calls never wait on Google."
        actions={
          configured && items.length > 0 ? (
            <Button icon={<Plug />} onClick={() => connect.mutate(undefined)} pending={connect.isPending}>
              Connect another Google account
            </Button>
          ) : undefined
        }
      />
      {list.isPending ? (
        <Skeleton className="h-48 w-full rounded-panel" />
      ) : list.isError ? (
        <EmptyState icon={<Cloud />} title="Connections did not load">
          {problemMessage(list.error, "connection")}
        </EmptyState>
      ) : !configured ? (
        <EmptyState icon={<Cloud />} title="Google Drive is not configured on this server">
          An administrator needs to add a Google OAuth client before workspaces can connect Google accounts.
        </EmptyState>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<Cloud />}
          title="Connect Google"
          actions={
            <Button variant="primary" icon={<Plug />} onClick={() => connect.mutate(undefined)} pending={connect.isPending}>
              Connect Google
            </Button>
          }
        >
          Connect a Google account to keep knowledge bases in step with folders in Google Drive. Callwright asks for read-only Drive access, and for
          Google Sheets access that stays unused until the Google Sheets tool is turned on.
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          {items.map((c) => (
            <ConnectionCard key={c.id} connection={c} />
          ))}
        </div>
      )}
    </>
  );
}

export function ConnectionCard({ connection: c }: { connection: Connection }) {
  const qc = useQueryClient();
  const detail = useConnection(c.id);
  const connect = useStartConnect();
  const [confirm, setConfirm] = useState(false);
  const [inUse, setInUse] = useState<ConnectionUser[] | null>(null);
  const health = HEALTH[c.health];
  const driveGranted = c.scopes.includes(DRIVE_SCOPE);
  const users = detail.data?.users ?? [];

  const test = useMutation({
    mutationFn: () => testConnection(c.id),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: connectionKeys.all });
      toast({
        tone: updated.health === "healthy" ? "success" : "error",
        title: updated.health === "healthy" ? "Connection works" : "Google access is not working",
        description: updated.health === "healthy" ? undefined : "Reconnect the Google account to fix it.",
      });
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteConnection(c.id),
    onSuccess: () => {
      setConfirm(false);
      qc.invalidateQueries({ queryKey: connectionKeys.all });
      toast({ tone: "success", title: "Connection removed" });
    },
    onError: (err) => {
      if (isApiError(err) && err.problem?.code === "connection_in_use") {
        setInUse((err.problem as { users?: ConnectionUser[] }).users ?? users);
        setConfirm(false);
        return;
      }
      toast({ tone: "error", title: "Could not remove the connection", description: problemMessage(err, "connection") });
    },
  });

  return (
    <Panel
      title={c.account_email}
      // Health describes the account, so it sits with it; the actions on the right are all one kind of button.
      description={
        <span className="flex flex-wrap items-center gap-2">
          Google account
          <Badge tone={health.tone} icon={health.icon}>
            {health.label}
          </Badge>
        </span>
      }
      icon={<Cloud />}
      bodyClassName="p-0"
      actions={
        <>
          <Button size="sm" icon={<Activity />} onClick={() => test.mutate()} pending={test.isPending}>
            Test
          </Button>
          {(c.health !== "healthy" || !c.sheets_access) && (
            <Button size="sm" icon={<RefreshCw />} onClick={() => connect.mutate(c.id)} pending={connect.isPending}>
              Reconnect
            </Button>
          )}
          <Button size="sm" icon={<Trash2 />} aria-label={`Remove ${c.account_email}`} onClick={() => setConfirm(true)}>
            Remove
          </Button>
        </>
      }
    >
      {/* Three facts side by side, each value under its label, rather than label-left/value-right rows
          that leave a gap across the whole card. */}
      <FactGrid className="md:grid-cols-3">
        <Fact icon={<ShieldCheck />} label="Access">
          <span className="flex flex-wrap items-center gap-1.5">
            {driveGranted && <Badge icon={<Database />}>{SCOPE_LABELS[DRIVE_SCOPE]}</Badge>}
            {c.sheets_access ? (
              <Badge icon={<Table2 />}>Sheets</Badge>
            ) : (
              <Badge tone="warning" icon={<Table2 />}>
                Sheets access not granted
              </Badge>
            )}
          </span>
          <span className="mt-2 block text-[13px] leading-relaxed text-fg-3">
            {c.sheets_access
              ? "Sheets access is not used until the Google Sheets tool is turned on."
              : "Reconnect and allow Sheets access to use the Google Sheets tool later. Knowledge sync works without it."}
          </span>
        </Fact>
        <Fact icon={<CircleCheck />} label="Last worked">
          <span className="text-fg">{c.last_success_at ? timeAgo(c.last_success_at) : "Not yet"}</span>
          {c.health_reason && c.health !== "healthy" && (
            <span className="mt-1 block text-[13px] text-fg-3">{c.health_reason.replace(/_/g, " ")}</span>
          )}
        </Fact>
        <Fact icon={<Link2 />} label="Used by">
          {users.length === 0 ? (
            <span className="text-fg-3">No knowledge bases yet</span>
          ) : (
            <ul className="flex flex-col gap-1">
              {users.map((u) => (
                <li key={u.source_id}>
                  <Link className="link-underline text-accent-text" to={knowledgeBasePath(u.kb_id)}>
                    {u.kb_name}
                  </Link>
                  <span className="text-fg-3"> from {u.root_name}</span>
                </li>
              ))}
            </ul>
          )}
        </Fact>
      </FactGrid>
      {inUse && (
        <div role="alert" className="border-t border-line px-5 py-3 text-[13px] text-danger-text">
          This connection is used by {inUse.map((u) => u.kb_name).join(", ")}. Remove those Google Drive sources first.
        </div>
      )}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Remove this connection?"
        description={`Callwright will stop using ${c.account_email} and revoke its access at Google.`}
        confirmLabel="Remove connection"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </Panel>
  );
}

export { CONNECTIONS_PATH };
