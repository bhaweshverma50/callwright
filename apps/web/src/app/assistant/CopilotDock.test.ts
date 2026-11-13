import { describe, expect, it } from "vitest";
import { nearestSide, pinnedOffset } from "./CopilotDock";

// A 200x48 dock in a 1000x800 window; offsets are measured from its bottom-right home, 16px in.
const W = 1000;
const H = 800;
const box = (left: number, top: number) => ({ left, top, right: left + 200, bottom: top + 48 });

describe("dock edge snapping", () => {
  it("picks the closest window edge", () => {
    expect(nearestSide(box(20, 300), W, H)).toBe("left");
    expect(nearestSide(box(780, 300), W, H)).toBe("right");
    expect(nearestSide(box(400, 10), W, H)).toBe("top");
    expect(nearestSide(box(400, 740), W, H)).toBe("bottom");
  });

  it("pins flush to an edge and keeps its place along it, inside the window", () => {
    expect(pinnedOffset("right", -300, -200, 200, 48, W, H)).toEqual({ x: 0, y: -200 });
    expect(pinnedOffset("left", -300, -200, 200, 48, W, H)).toEqual({ x: -768, y: -200 });
    expect(pinnedOffset("bottom", -300, -200, 200, 48, W, H)).toEqual({ x: -300, y: 0 });
    expect(pinnedOffset("top", -300, -200, 200, 48, W, H)).toEqual({ x: -300, y: -720 });
    // Past the far end of the edge it stops at the corner.
    expect(pinnedOffset("right", 0, -5000, 200, 48, W, H)).toEqual({ x: 0, y: -720 });
  });
});
