import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Cloud, Folder, HardDrive, Plug } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { useConnections } from "../../../api/connections";
import { createSource, kbKeys, sourceKeys, useDriveFolders, useSharedDrives } from "../../../api/knowledge";
import { problemMessage } from "../../../api/problems";
import { Button, Dialog, EmptyState, FieldRow, PanelRows, Select, Skeleton, SwitchControl, toast } from "../../../components";
import { cn, focusRing } from "../../../components/cn";
import { CONNECTIONS_PATH } from "../../../lib/paths";

interface Crumb {
  id: string;
  name: string;
}

type Choice = { kind: "folder"; id: string; name: string; driveId: string | null } | { kind: "shared_drive"; id: string; name: string };

/**
 * Add a Google Drive folder or shared drive as a source on a knowledge base (022 US2). The folder
 * browser lists folders only; the first sync starts as soon as the source is added.
 */
export function AddDriveSourceDialog({
  open,
  onOpenChange,
  kbId,
  kbName,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kbId: string;
  kbName: string;
}) {
  const qc = useQueryClient();
  const connections = useConnections();
  const usable = (connections.data?.items ?? []).filter((c) => c.health !== "revoked");
  const [connectionId, setConnectionId] = useState<string | undefined>();
  const [drive, setDrive] = useState<{ id: string; name: string } | null>(null);
  const [trail, setTrail] = useState<Crumb[]>([]);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [subfolders, setSubfolders] = useState(true);
  const subId = useId();

  useEffect(() => {
    if (open && !connectionId && usable[0]) setConnectionId(usable[0].id);
  }, [open, connectionId, usable]);
  useEffect(() => {
    if (!open) {
      setDrive(null);
      setTrail([]);
      setChoice(null);
      setSubfolders(true);
    }
  }, [open]);

  const parent = trail.at(-1)?.id ?? "root";
  const folders = useDriveFolders(open ? connectionId : undefined, parent, drive?.id ?? null);
  const drives = useSharedDrives(open && !drive && trail.length === 0 ? connectionId : undefined);

  const add = useMutation({
    mutationFn: () =>
      createSource(kbId, {
        connection_id: connectionId!,
        root_kind: choice!.kind,
        root_id: choice!.id,
        drive_id: choice!.kind === "folder" ? choice!.driveId : choice!.id,
        include_subfolders: choice!.kind === "shared_drive" ? true : subfolders,
      }),
    onSuccess: (src) => {
      qc.invalidateQueries({ queryKey: sourceKeys.list(kbId) });
      qc.invalidateQueries({ queryKey: kbKeys.all });
      toast({ tone: "success", title: "Drive source added", description: `${src.root_name} is syncing into ${kbName}.` });
      onOpenChange(false);
    },
  });

  const open_folder = (f: Crumb) => {
    setTrail((t) => [...t, f]);
    setChoice({ kind: "folder", id: f.id, name: f.name, driveId: drive?.id ?? null });
  };
  const go_to = (index: number) => {
    const next = trail.slice(0, index);
    setTrail(next);
    const last = next.at(-1);
    setChoice(
      last ? { kind: "folder", id: last.id, name: last.name, driveId: drive?.id ?? null } : drive ? { kind: "shared_drive", ...drive } : null,
    );
  };

  const noConnection = connections.isSuccess && usable.length === 0;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !add.isPending && onOpenChange(o)}
      size="lg"
      icon={<Cloud />}
      title="Add a Google Drive source"
      description={`Pick a folder or shared drive. Its Google Docs, PDFs and Word files sync into ${kbName}, and only agents with ${kbName} attached can search them.`}
      footer={
        noConnection ? undefined : (
          <>
            <Button onClick={() => onOpenChange(false)} disabled={add.isPending}>
              Cancel
            </Button>
            <Button variant="primary" disabled={!choice || !connectionId} pending={add.isPending} onClick={() => add.mutate()}>
              {choice ? `Sync ${choice.name}` : "Choose a folder"}
            </Button>
          </>
        )
      }
    >
      {connections.isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : noConnection ? (
        <EmptyState
          compact
          icon={<Plug />}
          title="Connect Google first"
          actions={
            <Button asChild variant="primary">
              <Link to={CONNECTIONS_PATH}>Go to Connections</Link>
            </Button>
          }
        >
          A Google account gives Callwright read-only access to the folders you choose.
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-4">
          {usable.length > 1 && (
            <Select
              aria-label="Google account"
              value={connectionId}
              onValueChange={(v) => {
                setConnectionId(v);
                setDrive(null);
                setTrail([]);
                setChoice(null);
              }}
              options={usable.map((c) => ({ value: c.id, label: c.account_email }))}
            />
          )}
          <nav aria-label="Folder path" className="flex flex-wrap items-center gap-1 text-[13px]">
            <button
              type="button"
              className={cn("rounded-inline px-1 text-accent-text hover:underline", focusRing)}
              onClick={() => {
                setDrive(null);
                setTrail([]);
                setChoice(null);
              }}
            >
              {drive ? "Drives" : "My Drive"}
            </button>
            {drive && (
              <>
                <ChevronRight className="size-3.5 text-fg-3" aria-hidden />
                <button type="button" className={cn("rounded-inline px-1 text-accent-text hover:underline", focusRing)} onClick={() => go_to(0)}>
                  {drive.name}
                </button>
              </>
            )}
            {trail.map((c, i) => (
              <span key={c.id} className="flex items-center gap-1">
                <ChevronRight className="size-3.5 text-fg-3" aria-hidden />
                <button type="button" className={cn("rounded-inline px-1 text-accent-text hover:underline", focusRing)} onClick={() => go_to(i + 1)}>
                  {c.name}
                </button>
              </span>
            ))}
          </nav>
          <ul className="flex max-h-72 flex-col overflow-y-auto rounded-control border border-line" aria-label="Folders">
            {folders.isPending ? (
              <li className="p-3">
                <Skeleton className="h-6 w-full" />
              </li>
            ) : folders.isError ? (
              <li className="p-3 text-[13px] text-danger-text">{problemMessage(folders.error, "folder")}</li>
            ) : (
              <>
                {!drive &&
                  trail.length === 0 &&
                  drives.data?.items.map((d) => (
                    <FolderRow
                      key={d.id}
                      icon={<HardDrive />}
                      name={d.name}
                      hint="Shared drive"
                      onOpen={() => {
                        setDrive({ id: d.id, name: d.name });
                        setChoice({ kind: "shared_drive", id: d.id, name: d.name });
                      }}
                    />
                  ))}
                {folders.data.items.map((f) => (
                  <FolderRow key={f.id} icon={<Folder />} name={f.name} onOpen={() => open_folder({ id: f.id, name: f.name })} />
                ))}
                {folders.data.items.length === 0 && (drive || trail.length > 0 || !drives.data?.items.length) && (
                  <li className="px-3 py-2.5 text-[13px] text-fg-3">No folders inside. You can sync this one.</li>
                )}
              </>
            )}
          </ul>
          {choice?.kind === "folder" && (
            <PanelRows>
              <FieldRow label="Include subfolders" htmlFor={subId} description="Files in folders inside this one sync too, at any depth.">
                <SwitchControl id={subId} checked={subfolders} onCheckedChange={setSubfolders} />
              </FieldRow>
            </PanelRows>
          )}
          {add.error && (
            <p role="alert" className="text-[13px] text-danger-text">
              {problemMessage(add.error, "source")}
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
}

function FolderRow({ icon, name, hint, onOpen }: { icon: React.ReactNode; name: string; hint?: string; onOpen: () => void }) {
  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={onOpen}
        className={cn("flex w-full items-center gap-2.5 px-3 py-2.5 text-left text-[13px] text-fg hover:bg-surface-2 [&_svg]:size-4", focusRing)}
      >
        <span className="text-fg-3">{icon}</span>
        <span className="min-w-0 flex-1 truncate">{name}</span>
        {hint && <span className="text-[12px] text-fg-3">{hint}</span>}
        <ChevronRight className="text-fg-3" aria-hidden />
      </button>
    </li>
  );
}
