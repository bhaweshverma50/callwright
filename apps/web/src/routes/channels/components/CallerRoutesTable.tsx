import { Plus, Search, Trash2, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { isApiError } from "../../../api/errors";
import { problemMessage } from "../../../api/problems";
import { Badge, Button, IconButton, Input, Skeleton, Tooltip, toast } from "../../../components";
import { useDebounced } from "../../../lib/useDebounced";
import { useCallerRoutes, useRouteMutations } from "../../../api/channels";
import { AgentSelect } from "./shared";
import { useAllAgents } from "../../../api/agents";

/**
 * Caller routes of one WhatsApp channel (010 T060, FR-028): search, add, change the agent,
 * remove. A route whose agent is no longer published is skipped (the default agent answers).
 */
export function CallerRoutesTable({ channelId, disabled }: { channelId: string; disabled?: boolean }) {
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 250);
  const routes = useCallerRoutes(channelId, q);
  const agents = useAllAgents();
  const { create, update, remove } = useRouteMutations(channelId);
  const [caller, setCaller] = useState("");
  const [agent, setAgent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const add = () => {
    setError(null);
    if (!caller.trim()) return setError("Enter the caller's WhatsApp number.");
    if (!agent) return setError("Choose the agent for this caller.");
    create.mutate(
      { caller_number: caller.trim(), agent_id: agent },
      {
        onSuccess: () => {
          setCaller("");
          setAgent(null);
        },
        onError: (err) =>
          setError(
            isApiError(err) && err.problem.code === "duplicate_caller_route"
              ? "This caller already has a route."
              : isApiError(err) && err.problem.code === "route_limit_reached"
                ? "A channel holds at most 1,000 caller routes."
                : (isApiError(err) && err.problem.errors?.[0]?.message) || problemMessage(err, "caller route"),
          ),
      },
    );
  };

  const items = routes.data?.items ?? [];
  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-2 rounded-panel border border-dashed border-line-strong bg-surface-2/50 p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Input
          inputSize="sm"
          className="font-mono"
          placeholder="+14155550123"
          aria-label="Caller number"
          disabled={disabled}
          value={caller}
          onChange={(e) => {
            setCaller(e.target.value);
            setError(null);
          }}
        />
        <AgentSelect size="sm" aria-label="Agent for this caller" value={agent} onValueChange={setAgent} agents={agents.data} disabled={disabled} />
        <Button size="sm" icon={<Plus aria-hidden />} pending={create.isPending} disabled={disabled} onClick={add}>
          Add route
        </Button>
        {error && (
          <p role="alert" className="text-[13px] text-danger-text sm:col-span-3">
            {error}
          </p>
        )}
      </div>
      {(routes.data?.total ?? 0) > 5 || q ? (
        <Input
          inputSize="sm"
          prefix={<Search aria-hidden />}
          placeholder="Search caller numbers"
          aria-label="Search caller numbers"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          suffix={
            search ? (
              <IconButton label="Clear search" className="size-6 [&_svg]:size-3.5" onClick={() => setSearch("")}>
                <X aria-hidden />
              </IconButton>
            ) : undefined
          }
        />
      ) : null}
      {routes.isPending ? (
        <Skeleton className="h-20 w-full rounded-panel" />
      ) : items.length === 0 ? (
        <p className="px-1 text-[13px] text-fg-3">
          {q ? `No caller numbers match "${q}".` : "No caller routes. Every caller reaches the default agent."}
        </p>
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-panel border border-line">
          <AnimatePresence initial={false}>
            {items.map((r) => (
              <motion.li
                key={r.id}
                layout
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, height: 0 }}
                className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-2 bg-surface px-3 py-2.5 transition-colors hover:bg-accent-soft/25 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_auto]"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate font-mono text-[13px] text-fg">{r.caller_number}</span>
                  {r.agent_published === false && (
                    <Tooltip content="This agent has no published version, so the default agent answers instead.">
                      <span>
                        <Badge tone="warning">Skipped</Badge>
                      </span>
                    </Tooltip>
                  )}
                </div>
                <AgentSelect
                  size="sm"
                  className="col-span-2 row-start-2 sm:col-span-1 sm:row-start-auto"
                  aria-label={`Agent for ${r.caller_number}`}
                  value={r.agent_id}
                  agents={agents.data}
                  disabled={disabled}
                  onValueChange={(v) =>
                    v &&
                    update.mutate(
                      { id: r.id, agent_id: v },
                      { onError: (err) => toast({ tone: "error", title: "Route not changed", description: problemMessage(err, "caller route") }) },
                    )
                  }
                />
                <IconButton label={`Remove route for ${r.caller_number}`} disabled={disabled} onClick={() => remove.mutate(r.id)}>
                  <Trash2 className="size-4" aria-hidden />
                </IconButton>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </div>
  );
}
