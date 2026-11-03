import { CalendarClock, History } from "lucide-react";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";
import { useScheduledCallbackCount } from "../../api/callbacks";
import { TabPanel, Tabs } from "../../components";

export type CallsView = "history" | "callbacks";

/**
 * The two views of the Calls area: every call (`/calls`), and the callbacks agents or the API
 * booked for later (`/calls/callbacks`). Each view is its own address because `?tab=` already
 * belongs to the call drawer. The Callbacks count is how many are still waiting to be placed.
 */
export function CallsTabs({ value, children }: { value: CallsView; children: ReactNode }) {
  const navigate = useNavigate();
  const scheduled = useScheduledCallbackCount();
  return (
    <Tabs
      aria-label="Calls"
      value={value}
      onValueChange={(v) => navigate(v === "callbacks" ? "/calls/callbacks" : "/calls")}
      items={[
        { value: "history", label: "History", icon: <History aria-hidden /> },
        {
          value: "callbacks",
          label: "Callbacks",
          icon: <CalendarClock aria-hidden />,
          ...(scheduled.data ? { count: scheduled.data } : {}),
        },
      ]}
    >
      <TabPanel value={value}>{children}</TabPanel>
    </Tabs>
  );
}
