import { STOCK_END_MESSAGE } from "../../model";
import type { ConfigByNode, FlowNode, LlmLabeler } from "./summaryTypes";

/** The one-line summary on a node card (FR-057): its key setting. */
export function nodeSummary(node: FlowNode, modelLabel?: LlmLabeler): string {
  const c = node.config as ConfigByNode[typeof node.type];
  switch (node.type) {
    case "start": {
      const s = c as ConfigByNode["start"];
      const greeting = s.greeting?.trim() ?? "";
      if (s.start_speaker === "user") return greeting ? `Caller first, after "${greeting}"` : "Caller speaks first";
      return s.greeting_type === "generated" ? "Agent first, greeting written by the next step" : `Agent: "${greeting || "no greeting yet"}"`;
    }
    case "agent":
    case "task": {
      const a = c as ConfigByNode["agent"];
      const llm = a.overrides?.llm;
      const parts: string[] = [];
      if (node.type === "task") {
        const t = c as ConfigByNode["task"];
        parts.push(`${t.fields.length} field${t.fields.length === 1 ? "" : "s"}, up to ${t.max_rounds} rounds`);
      }
      if (llm?.provider && llm.model) parts.push(modelLabel?.(llm.provider, llm.model) ?? llm.model);
      if (a.overrides?.language) parts.push(a.overrides.language);
      if (!parts.length) parts.push(a.instructions.trim() ? a.instructions.trim() : "No instructions yet");
      return parts.join(" · ");
    }
    case "condition": {
      const k = c as ConfigByNode["condition"];
      return k.kind === "rule"
        ? "Rules on variables, then otherwise"
        : `Classify: ${(k.categories ?? []).map((x) => x.name).join(", ") || "no categories"}`;
    }
    case "say": {
      const s = c as ConfigByNode["say"];
      return s.message.trim() ? `"${s.message.trim()}"` : "No message yet";
    }
    case "extract_variable": {
      const e = c as ConfigByNode["extract_variable"];
      return e.fields.length ? e.fields.map((f) => `{{${f.name}}}`).join(" ") : "No variables yet";
    }
    case "webhook": {
      const w = c as ConfigByNode["webhook"];
      return w.request.url ? `${w.request.method} ${w.request.url.replace(/^https?:\/\//, "")}` : "No URL yet";
    }
    case "transfer": {
      const t = (c as ConfigByNode["transfer"]).transfer;
      const kind = t.transfer_type === "warm" ? "Warm" : "Cold";
      return t.routing_type === "dynamic" ? `${kind}, number chosen by the agent` : `${kind} to ${t.number || "no number yet"}`;
    }
    case "end": {
      const e = c as ConfigByNode["end"];
      const message = e.message.trim();
      return message && message !== STOCK_END_MESSAGE ? `"${message}"` : `Agent says goodbye in its own words (${e.reason})`;
    }
  }
}
