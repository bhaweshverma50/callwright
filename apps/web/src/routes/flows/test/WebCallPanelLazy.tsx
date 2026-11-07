import { lazy, Suspense } from "react";
import { Skeleton } from "../../../components";

const Panel = lazy(() => import("../../../webCall/WebCallPanel").then((m) => ({ default: m.WebCallPanel })));

/** 003's web call panel, loaded when the Test tab first opens. */
export function WebCallPanelLazy(props: { agentId: string; version: string }) {
  return (
    <Suspense fallback={<Skeleton className="h-[320px] w-full rounded-panel" />}>
      <Panel {...props} />
    </Suspense>
  );
}
