import { expect, test, type Page } from "@playwright/test";
import { signIn } from "./helpers";

// Every FlowChain (pricing chain, home live call, placeholder loop, agent cost chain, gallery variants) has equal
// connectors: same length within 1px, same gap to the circles on both sides, on the circle
// centre line. Checked at 1440, 1024 and 390 wide.

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}
interface FlowGeometry {
  segs: Box[];
  discs: Box[];
}

async function flows(page: Page): Promise<FlowGeometry[]> {
  return page.$$eval(".flow", (els) =>
    els
      .filter((el) => (el as HTMLElement).offsetParent !== null)
      .map((el) => {
        const box = (n: Element) => {
          const r = n.getBoundingClientRect();
          return { x: r.x, y: r.y, w: r.width, h: r.height };
        };
        return {
          segs: Array.from(el.querySelectorAll(".flow-seg"), box),
          discs: Array.from(el.querySelectorAll("[data-flow-disc]"), box),
        };
      }),
  );
}

function check({ segs, discs }: FlowGeometry, where: string) {
  expect(discs.length, where).toBe(segs.length + 1);
  const horizontal = segs.every((s) => s.w >= s.h);
  const lengths = segs.map((s) => (horizontal ? s.w : s.h));
  const gapsBefore: number[] = [];
  const gapsAfter: number[] = [];
  segs.forEach((s, i) => {
    const a = discs[i]!;
    const b = discs[i + 1]!;
    if (horizontal) {
      gapsBefore.push(s.x - (a.x + a.w));
      gapsAfter.push(b.x - (s.x + s.w));
      expect(Math.abs(s.y + s.h / 2 - (a.y + a.h / 2)), `${where}: segment ${i} off the centre line`).toBeLessThanOrEqual(1);
    } else {
      gapsBefore.push(s.y - (a.y + a.h));
      gapsAfter.push(b.y - (s.y + s.h));
      expect(Math.abs(s.x + s.w / 2 - (a.x + a.w / 2)), `${where}: segment ${i} off the centre axis`).toBeLessThanOrEqual(1);
    }
  });
  const spread = (xs: number[]) => Math.max(...xs) - Math.min(...xs);
  expect(spread(lengths), `${where}: connector lengths ${lengths.map((l) => l.toFixed(1)).join(", ")}`).toBeLessThanOrEqual(1);
  expect(
    spread([...gapsBefore, ...gapsAfter]),
    `${where}: gaps ${[...gapsBefore, ...gapsAfter].map((g) => g.toFixed(1)).join(", ")}`,
  ).toBeLessThanOrEqual(1);
  expect(Math.min(...lengths), `${where}: connectors too short`).toBeGreaterThan(4);
}

for (const width of [1440, 1024, 390]) {
  test.describe(`flow chains at ${width}`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("public pages and the gallery", async ({ page }) => {
      for (const path of ["/", "/pricing", "/dev/components"]) {
        await page.goto(path);
        await page.waitForLoadState("networkidle");
        const found = await flows(page);
        expect(found.length, `${path} has flow chains`).toBeGreaterThan(0);
        found.forEach((f, i) => check(f, `${path} #${i} at ${width}`));
      }
    });

    test("the placeholder loop", async ({ page }) => {
      await signIn(page, "/calls");
      await page.waitForLoadState("networkidle");
      const found = await flows(page);
      expect(found.length).toBe(1);
      check(found[0]!, `/calls at ${width}`);
    });

    test("the agent editor's cost chain", async ({ page }) => {
      await signIn(page, "/agents/new/single");
      await expect(page.getByText("Total a minute")).toBeVisible();
      await page.waitForLoadState("networkidle");
      const found = await flows(page);
      expect(found.length).toBe(1);
      check(found[0]!, `/agents/new/single at ${width}`);
    });
  });
}
