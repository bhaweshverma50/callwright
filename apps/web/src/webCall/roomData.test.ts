import { describe, expect, it, vi } from "vitest";
import { onRoomData, publishRoomData, ROOM_TOPICS } from "./roomData";

const bytes = (v: unknown) => new TextEncoder().encode(typeof v === "string" ? v : JSON.stringify(v));

describe("room data", () => {
  it("takes the topics from the contract", () => {
    expect(ROOM_TOPICS).toEqual({ latency: "cw.turn_latency", flow: "callwright.flow" });
  });

  it("hands decoded messages to the listeners of their topic only", () => {
    const flow = vi.fn();
    const latency = vi.fn();
    const offFlow = onRoomData("flow", flow);
    const offLatency = onRoomData("latency", latency);
    publishRoomData(ROOM_TOPICS.flow, bytes({ type: "node_entered", node_id: "n_a", at_ms: 5 }));
    expect(flow).toHaveBeenCalledWith({ type: "node_entered", node_id: "n_a", at_ms: 5 });
    expect(latency).not.toHaveBeenCalled();
    publishRoomData("some.other.topic", bytes({}));
    publishRoomData(undefined, bytes({}));
    expect(flow).toHaveBeenCalledTimes(1);
    offFlow();
    offLatency();
    publishRoomData(ROOM_TOPICS.flow, bytes({ type: "node_entered", node_id: "n_b", at_ms: 6 }));
    expect(flow).toHaveBeenCalledTimes(1);
  });

  it("ignores a message that is not JSON", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const latency = vi.fn();
    const off = onRoomData("latency", latency);
    publishRoomData(ROOM_TOPICS.latency, bytes("not json"));
    expect(latency).not.toHaveBeenCalled();
    off();
    warn.mockRestore();
  });
});
